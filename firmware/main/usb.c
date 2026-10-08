/* The nesp32's files, lent to a computer as a USB drive.
 *
 * Only a StickS3 can: its USB port is the chip's own. A StickC Plus2's is a
 * serial port made by another chip, and can be nothing else.
 *
 * The chip's USB is one port with two uses. Until it is asked for, it is
 * the serial port the firmware is flashed and watched through, and this
 * leaves it so. When the console asks (the setup ROM's USB screen), the
 * files are closed and unmounted, and the port becomes a drive of the
 * `storage` partition, whose FAT filing system the computer reads and
 * writes for itself. The nesp32 has no files meanwhile.
 *
 * It stops being a drive by restarting: told to by the console, or because
 * the computer ejected it or the cable came out. The files are mounted and
 * listed again as at any start, with whatever was copied.
 *
 * Restarting does not by itself give the port back. Which of its two uses
 * the port has is kept where a restart does not reach, and only the power
 * going off clears it: a StickS3 that had been a drive was no serial port
 * until it was switched off and on. So the port is given back here, before
 * the restart, and at every start as well, for a restart that was not this
 * file's doing.
 */
#include "usb.h"

#include "sdkconfig.h"

#if CONFIG_IDF_TARGET_ESP32S3

#include "esp_log.h"
#include "esp_partition.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "soc/rtc_cntl_struct.h"
#include "tinyusb.h"
#include "tinyusb_default_config.h"
#include "tinyusb_msc.h"
#include "wear_levelling.h"

#include "store.h"

#define RESTART_MS 500              /* for the reply that said so to be sent, and seen */

static const char *TAG = "usb";

/* Each is written by one task and read by others, a byte at a time. */
static volatile uint8_t state = NESP_DRIVE_OFF;
static volatile bool start_asked;
static volatile bool stop_asked;
static volatile bool taken;         /* a computer has had it */

void usb_start(void)
{
    /* The port's pins to whichever use the chip was made with: the serial
     * port. TinyUSB takes them for the other when it is installed. */
    RTCCNTL.usb_conf.sw_hw_usb_phy_sel = 0;
    RTCCNTL.usb_conf.sw_usb_phy_sel = 0;
}

uint8_t usb_drive(void *ctx, uint8_t lend)
{
    (void)ctx;
    if (lend == NESP_LEND_START && state == NESP_DRIVE_OFF) {
        /* The link task is the one that reads the files, so here is where
         * it stops. */
        store_close();
        state = NESP_DRIVE_WAITING;
        start_asked = true;
    } else if (lend == NESP_LEND_STOP && state != NESP_DRIVE_OFF) {
        stop_asked = true;
    }
    return state;
}

uint8_t usb_drive_state(void)
{
    return state;
}

static void on_usb(tinyusb_event_t *event, void *arg)
{
    (void)arg;
    if (event->id == TINYUSB_EVENT_ATTACHED) {
        taken = true;
        state = NESP_DRIVE_MOUNTED;
    } else if (event->id == TINYUSB_EVENT_DETACHED && taken) {
        state = NESP_DRIVE_EJECTED;         /* the cable, or the computer, has gone */
    }
}

/* The component hands the files back to this end when the computer ejects
 * the drive. */
static void on_storage(tinyusb_msc_storage_handle_t handle, tinyusb_msc_event_t *event, void *arg)
{
    (void)handle;
    (void)arg;
    if (event->id == TINYUSB_MSC_EVENT_MOUNT_COMPLETE
        && event->mount_point == TINYUSB_MSC_STORAGE_MOUNT_APP && taken) {
        state = NESP_DRIVE_EJECTED;
    }
}

static bool start(void)
{
    static wl_handle_t wear = WL_INVALID_HANDLE;
    static tinyusb_msc_storage_handle_t storage;
    store_unmount();
    const esp_partition_t *partition = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_FAT, STORE_PARTITION);
    if (partition == NULL || wl_mount(partition, &wear) != ESP_OK) {
        return false;
    }
    tinyusb_msc_storage_config_t config = {
        .medium.wl_handle = wear,
        .mount_point = TINYUSB_MSC_STORAGE_MOUNT_USB,
        .fat_fs = {
            .base_path = STORE_BASE,
            .config.max_files = 4,
            .do_not_format = true,
        },
    };
    if (tinyusb_msc_new_storage_spiflash(&config, &storage) != ESP_OK
        || tinyusb_msc_set_storage_callback(on_storage, NULL) != ESP_OK) {
        return false;
    }
    tinyusb_config_t usb = TINYUSB_DEFAULT_CONFIG(on_usb);
    usb.task.xCoreID = 0;           /* core 1 is the link task's (link.c) */
    return tinyusb_driver_install(&usb) == ESP_OK;
}

void usb_poll(void)
{
    if (start_asked) {
        start_asked = false;
        if (start()) {
            ESP_LOGI(TAG, "the files are a drive");
        } else {
            ESP_LOGE(TAG, "the files could not be made a drive");
            stop_asked = true;
        }
    }
    if (stop_asked || state == NESP_DRIVE_EJECTED) {
        vTaskDelay(pdMS_TO_TICKS(RESTART_MS));
        usb_start();
        esp_restart();
    }
}

#else

void usb_start(void)
{
}

uint8_t usb_drive(void *ctx, uint8_t lend)
{
    (void)ctx;
    (void)lend;
    return NESP_DRIVE_NONE;
}

uint8_t usb_drive_state(void)
{
    return NESP_DRIVE_NONE;
}

void usb_poll(void)
{
}

#endif
