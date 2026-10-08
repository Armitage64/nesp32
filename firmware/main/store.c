/* The nesp32's files.
 *
 * The `storage` partition (partitions.csv) holds a FAT filing system, wear
 * levelled, mounted at /files: FAT because it is what a computer reads when
 * the partition is lent to it as a drive. The jukebox's tracks are the
 * files in /files/tracks, in the order of their names: .jbs and .pcm, which
 * are played as they are. A rip of a game's music put there, a .vgm or a
 * .vgz, is made into its .jbs at the next start, and that file takes the
 * rip's place: the same name with the other ending, and the rip is removed.
 * So a rip is converted once, and whoever looks at the drive sees what has
 * been. One that cannot be played is left as it was. tools/put_files.py at
 * the top of the tree writes the tracks there over USB.
 *
 * The tracks are listed once, at start, and read by the link task alone
 * (the jukebox's tick), which keeps the file it is reading open: a track is
 * read from end to end, a few dozen bytes at a time.
 */
#include "store.h"

#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_vfs_fat.h"
#include "miniz.h"
#include "wear_levelling.h"

#define BASE STORE_BASE
#define TRACKS BASE "/tracks"
#define PARTITION STORE_PARTITION
#define LABEL "NESP32"              /* the drive's name, on a computer */
#define TRACKS_MAX 200
#define RIP_MAX (1024 * 1024)       /* a rip, unpacked: those tried are 15 to 63 KB */

static const char *TAG = "store";

typedef struct {
    char *path;
    uint8_t *made;                  /* a rip's .jbs that could not be written to a file,
                                       and is played from here; NULL: the file is the track */
    uint32_t made_len;
} track_t;

static wl_handle_t wear = WL_INVALID_HANDLE;
static track_t tracks[TRACKS_MAX];
static uint16_t count;
static FILE *open_file;             /* the link task's: the track being read */
static uint16_t open_track;

static bool ends(const char *name, const char *suffix)
{
    size_t len = strlen(name);
    return len > 4 && strcasecmp(name + len - 4, suffix) == 0;
}

static bool is_rip(const char *name)
{
    return ends(name, ".vgm") || ends(name, ".vgz");
}

/* Not what a computer leaves beside the files it copies: a Mac's are named
 * for them, with "._" in front. */
static bool is_track(const char *name)
{
    return name[0] != '.' && (ends(name, ".jbs") || ends(name, ".pcm") || is_rip(name));
}

static int by_path(const void *a, const void *b)
{
    return strcmp(((const track_t *)a)->path, ((const track_t *)b)->path);
}

/* Memory for what is big, from the PSRAM if there is any. */
static void *big(size_t size)
{
    return heap_caps_malloc_prefer(size, 2, MALLOC_CAP_SPIRAM, MALLOC_CAP_DEFAULT);
}

static uint8_t *read_whole(const char *path, size_t *len)
{
    struct stat info;
    if (stat(path, &info) != 0 || info.st_size <= 0 || info.st_size > RIP_MAX) {
        return NULL;
    }
    uint8_t *data = big((size_t)info.st_size);
    FILE *file = data != NULL ? fopen(path, "rb") : NULL;
    if (file == NULL || fread(data, 1, (size_t)info.st_size, file) != (size_t)info.st_size) {
        free(data);
        data = NULL;
    }
    if (file != NULL) {
        fclose(file);
    }
    *len = (size_t)info.st_size;
    return data;
}

/* What a gzip file holds (a .vgz is a .vgm in one), or NULL. Its last four
 * bytes say how long that is. */
static uint8_t *unpack(const uint8_t *gz, size_t len, size_t *out_len)
{
    if (len < 18 || gz[2] != 8) {
        return NULL;
    }
    uint8_t flags = gz[3];
    size_t at = 10;
    if (flags & 0x04) {             /* extra */
        at += 2u + (gz[at] | (size_t)gz[at + 1] << 8);
    }
    for (uint8_t text = 0x08; text <= 0x10; text <<= 1) {
        if (flags & text) {         /* the file's name, and a comment */
            while (at < len && gz[at] != 0) {
                at++;
            }
            at++;
        }
    }
    if (flags & 0x02) {             /* the header's CRC */
        at += 2;
    }
    if (at + 8 > len) {
        return NULL;
    }
    const uint8_t *tail = gz + len - 4;
    size_t size = tail[0] | (size_t)tail[1] << 8 | (size_t)tail[2] << 16 | (size_t)tail[3] << 24;
    if (size == 0 || size > RIP_MAX) {
        return NULL;
    }
    uint8_t *out = big(size);
    tinfl_decompressor *inflater = big(sizeof(*inflater));
    size_t in_len = len - 8 - at;
    size_t made = size;
    if (out != NULL && inflater != NULL) {
        tinfl_init(inflater);
        if (tinfl_decompress(inflater, gz + at, &in_len, out, out, &made,
                             TINFL_FLAG_USING_NON_WRAPPING_OUTPUT_BUF) != TINFL_STATUS_DONE
            || made != size) {
            free(out);
            out = NULL;
        }
    } else {
        free(out);
        out = NULL;
    }
    free(inflater);
    *out_len = size;
    return out;
}

/* A rip's .jbs, into memory. False: it is not a rip that can be played. */
static bool make(track_t *track, nesp_vgm_t *work)
{
    size_t len = 0;
    uint8_t *rip = read_whole(track->path, &len);
    if (rip != NULL && len >= 2 && rip[0] == 0x1F && rip[1] == 0x8B) {
        uint8_t *packed = rip;
        rip = unpack(packed, len, &len);
        free(packed);
    }
    if (rip == NULL) {
        return false;
    }
    /* Its title, if it has none of its own: the file's name without the
     * directory and the suffix. */
    char name[NESP_JUKE_NAME];
    const char *file = strrchr(track->path, '/') + 1;
    snprintf(name, sizeof(name), "%.*s", (int)(strlen(file) - 4), file);
    /* A write is three bytes of a rip and at most four of the stream. */
    size_t room = 2 * len + 4096;
    uint8_t *made = big(room);
    size_t made_len = 0;
    bool done = made != NULL && nesp_vgm_to_jbs(work, rip, len, name, made, room, &made_len);
    free(rip);
    if (done) {
        track->made = big(made_len);
        if (track->made != NULL) {
            memcpy(track->made, made, made_len);
            track->made_len = (uint32_t)made_len;
        }
    }
    free(made);
    return track->made != NULL;
}

/* A rip's .jbs, as a file in the rip's place. False, and the rip is left
 * and its .jbs kept in memory for now, if it could not be written: the
 * files are full. */
static bool keep(track_t *track)
{
    char *path = strdup(track->path);
    if (path == NULL) {
        return false;
    }
    memcpy(path + strlen(path) - 4, ".jbs", 4);
    /* Not the C library's files: on a StickC Plus2 that library is in the
     * little memory code can run from while the flash is busy, and its
     * writing would not fit there. */
    int file = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0664);
    bool written = file >= 0
                   && write(file, track->made, track->made_len) == (ssize_t)track->made_len;
    if (file >= 0) {
        written = close(file) == 0 && written;
    }
    if (!written) {
        unlink(path);
        free(path);
        return false;
    }
    unlink(track->path);
    free(track->path);
    free(track->made);
    track->path = path;
    track->made = NULL;
    track->made_len = 0;
    return true;
}

/* A file that says something by being there. */
static void leave(const char *path)
{
    struct stat info;
    if (stat(path, &info) != 0) {
        FILE *file = fopen(path, "wb");
        if (file != NULL) {
            fclose(file);
        }
    }
}

void store_start(store_progress_t progress)
{
    const esp_vfs_fat_mount_config_t config = {
        .format_if_mount_failed = true,
        .max_files = 4,
        .allocation_unit_size = CONFIG_WL_SECTOR_SIZE,
    };
    esp_err_t error = esp_vfs_fat_spiflash_mount_rw_wl(BASE, PARTITION, &config, &wear);
    if (error != ESP_OK) {
        ESP_LOGE(TAG, "no files: %s", esp_err_to_name(error));
        return;
    }
    /* What a computer calls the drive, where the tracks go, for whoever
     * opens it; and a Mac is told not to keep its indexes on a drive of
     * four megabytes. */
    char label[32] = "";
    if (f_getlabel("0:", label, NULL) == FR_OK && label[0] == 0) {
        f_setlabel("0:" LABEL);
    }
    mkdir(TRACKS, 0775);
    leave(BASE "/.metadata_never_index");
    mkdir(BASE "/.fseventsd", 0775);
    leave(BASE "/.fseventsd/no_log");

    unsigned rips = 0;
    DIR *dir = opendir(TRACKS);
    if (dir != NULL) {
        struct dirent *entry;
        while (count < TRACKS_MAX && (entry = readdir(dir)) != NULL) {
            if (is_track(entry->d_name)
                && asprintf(&tracks[count].path, TRACKS "/%s", entry->d_name) > 0) {
                rips += is_rip(entry->d_name);
                count++;
            }
        }
        closedir(dir);
        qsort(tracks, count, sizeof(tracks[0]), by_path);
    }
    /* The rips, each into its .jbs, which takes its place among the files.
     * One that cannot be played is no track. */
    nesp_vgm_t *work = rips != 0 ? big(sizeof(*work)) : NULL;
    unsigned tried = 0;
    uint16_t kept = 0;
    for (uint16_t index = 0; index < count; index++) {
        track_t track = tracks[index];
        if (is_rip(track.path)) {
            if (progress != NULL) {
                progress(++tried, rips);
            }
            if (work == NULL || !make(&track, work)) {
                ESP_LOGW(TAG, "%s is not a rip that can be played", track.path);
                free(track.path);
                continue;
            }
            if (!keep(&track)) {
                ESP_LOGW(TAG, "no room to keep %s converted", track.path);
            }
        }
        tracks[kept++] = track;
    }
    count = kept;
    free(work);
    /* In the order of their names as they now are; and a rip whose .jbs
     * was there already has taken its place, not a place beside it. */
    qsort(tracks, count, sizeof(tracks[0]), by_path);
    kept = 0;
    for (uint16_t index = 0; index < count; index++) {
        if (kept != 0 && strcmp(tracks[kept - 1].path, tracks[index].path) == 0) {
            free(tracks[index].path);
            continue;
        }
        tracks[kept++] = tracks[index];
    }
    count = kept;

    uint64_t total = 0;
    uint64_t unused = 0;
    esp_vfs_fat_info(BASE, &total, &unused);
    ESP_LOGI(TAG, "%u tracks, %u of them rips; %u KB of %u used", (unsigned)count, rips,
             (unsigned)((total - unused) / 1024), (unsigned)(total / 1024));
}

void store_close(void)
{
    if (open_file != NULL) {
        fclose(open_file);
        open_file = NULL;
    }
    count = 0;
}

void store_unmount(void)
{
    if (wear != WL_INVALID_HANDLE) {
        esp_vfs_fat_spiflash_unmount_rw_wl(BASE, wear);
        wear = WL_INVALID_HANDLE;
    }
}

uint16_t store_tracks(void *ctx)
{
    (void)ctx;
    return count;
}

uint32_t store_track_size(void *ctx, uint16_t track)
{
    struct stat info;
    (void)ctx;
    if (track >= count) {
        return 0;
    }
    if (tracks[track].made != NULL) {
        return tracks[track].made_len;
    }
    return stat(tracks[track].path, &info) == 0 ? (uint32_t)info.st_size : 0;
}

size_t store_track_read(void *ctx, uint16_t track, uint32_t offset, uint8_t *out, size_t len)
{
    (void)ctx;
    if (track >= count) {
        return 0;
    }
    if (tracks[track].made != NULL) {
        uint32_t size = tracks[track].made_len;
        if (offset >= size) {
            return 0;
        }
        if (len > size - offset) {
            len = size - offset;
        }
        memcpy(out, tracks[track].made + offset, len);
        return len;
    }
    if (open_file == NULL || open_track != track) {
        if (open_file != NULL) {
            fclose(open_file);
            open_file = NULL;
        }
        open_file = fopen(tracks[track].path, "rb");
        if (open_file == NULL) {
            return 0;
        }
        open_track = track;
    }
    if (fseek(open_file, (long)offset, SEEK_SET) != 0) {
        return 0;
    }
    return fread(out, 1, len, open_file);
}
