/* The nesp32's files.
 *
 * The `storage` partition (partitions.csv) holds a LittleFS filing system,
 * mounted at /files. The jukebox's tracks are the .jbs and .pcm files in
 * /files/tracks, in the order of their names; tools/put_files.py at the top
 * of the tree writes them there over USB.
 *
 * The tracks are listed once, at start, and read by the link task alone
 * (the jukebox's tick), which keeps the one it is reading open: a track is
 * read from end to end, a few dozen bytes at a time.
 */
#include "store.h"

#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "esp_littlefs.h"
#include "esp_log.h"

#define BASE "/files"
#define TRACKS BASE "/tracks"
#define PARTITION "storage"
#define TRACKS_MAX 200
#define PATH_MAX_LEN 96             /* TRACKS, a slash and a name of up to 64 */

static const char *TAG = "store";

static char *names[TRACKS_MAX];
static uint16_t count;
static FILE *open_file;             /* the link task's: the track being read */
static uint16_t open_track;

static bool is_track(const char *name)
{
    size_t len = strlen(name);
    return len > 4 && (strcmp(name + len - 4, ".jbs") == 0 || strcmp(name + len - 4, ".pcm") == 0);
}

static int by_name(const void *a, const void *b)
{
    return strcmp(*(char *const *)a, *(char *const *)b);
}

void store_start(void)
{
    const esp_vfs_littlefs_conf_t conf = {
        .base_path = BASE,
        .partition_label = PARTITION,
        .format_if_mount_failed = true,
    };
    esp_err_t error = esp_vfs_littlefs_register(&conf);
    if (error != ESP_OK) {
        ESP_LOGE(TAG, "no files: %s", esp_err_to_name(error));
        return;
    }
    DIR *dir = opendir(TRACKS);
    if (dir != NULL) {
        struct dirent *entry;
        while (count < TRACKS_MAX && (entry = readdir(dir)) != NULL) {
            if (is_track(entry->d_name)) {
                names[count] = strdup(entry->d_name);
                if (names[count] == NULL) {
                    break;
                }
                count++;
            }
        }
        closedir(dir);
        qsort(names, count, sizeof(names[0]), by_name);
    }
    size_t total = 0;
    size_t used = 0;
    esp_littlefs_info(PARTITION, &total, &used);
    ESP_LOGI(TAG, "%u tracks; %u KB of %u used", (unsigned)count, (unsigned)(used / 1024),
             (unsigned)(total / 1024));
}

static bool path_of(uint16_t track, char *path, size_t size)
{
    return track < count
           && snprintf(path, size, TRACKS "/%s", names[track]) < (int)size;
}

uint16_t store_tracks(void *ctx)
{
    (void)ctx;
    return count;
}

uint32_t store_track_size(void *ctx, uint16_t track)
{
    char path[PATH_MAX_LEN];
    struct stat info;
    (void)ctx;
    if (!path_of(track, path, sizeof(path)) || stat(path, &info) != 0) {
        return 0;
    }
    return (uint32_t)info.st_size;
}

size_t store_track_read(void *ctx, uint16_t track, uint32_t offset, uint8_t *out, size_t len)
{
    char path[PATH_MAX_LEN];
    (void)ctx;
    if (open_file == NULL || open_track != track) {
        if (open_file != NULL) {
            fclose(open_file);
            open_file = NULL;
        }
        if (!path_of(track, path, sizeof(path))) {
            return 0;
        }
        open_file = fopen(path, "rb");
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
