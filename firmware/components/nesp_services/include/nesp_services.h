/* The Stick's services, and what they ask of the hardware.
 *
 * A service answers the console from what it holds. Anything slow (joining
 * a network, a scan) is started through nesp_hal_t and asked after later;
 * none of these calls may wait. On the Stick the hal is the firmware's
 * (firmware/main); under the tests it is a stand-in (host/nesp_host.c).
 */
#ifndef NESP_SERVICES_H
#define NESP_SERVICES_H

#include "nesp_core.h"

#ifdef __cplusplus
extern "C" {
#endif

#define NESP_FIRMWARE_MAJOR 0
#define NESP_FIRMWARE_MINOR 1
#define NESP_FIRMWARE_PATCH 0
#define NESP_FIRMWARE_TEXT "0.1.0"

typedef struct {
    uint8_t state;                  /* NESP_WIFI_* */
    uint8_t why;                    /* NESP_WHY_*, when the state is FAILED */
    int8_t rssi;                    /* dBm; 0 when not joined */
    uint8_t address[4];             /* IPv4; zeros when not joined */
    uint8_t name_len;
    char name[NESP_NAME_MAX];       /* the saved network's name */
} nesp_wifi_t;

typedef struct {
    int8_t rssi;
    uint8_t auth;                   /* NESP_AUTH_* */
    uint8_t channel;
    uint8_t name_len;
    char name[NESP_NAME_MAX];
} nesp_network_t;

typedef struct {
    void *ctx;
    uint8_t (*board)(void *ctx);                    /* NESP_BOARD_* */
    const char *(*board_name)(void *ctx);
    uint8_t (*battery)(void *ctx);                  /* percent; 0xFF if unknown */
    bool (*time)(void *ctx, uint32_t *seconds);     /* since 1970; false if not known */
    void (*wifi)(void *ctx, nesp_wifi_t *out);
    bool (*scan_start)(void *ctx);                  /* false: cannot scan now */
    uint8_t (*scan_state)(void *ctx, uint8_t *count);   /* NESP_SCAN_* */
    bool (*scan_result)(void *ctx, uint8_t index, nesp_network_t *out);
    /* Save the network and start joining it. The password is not kept by
     * the caller. */
    bool (*join)(void *ctx, const char *name, uint8_t name_len,
                 const char *password, uint8_t password_len);
    void (*forget)(void *ctx);
    /* Shown on the Stick's screen: the application now on the console. */
    void (*app)(void *ctx, const char *id, uint8_t version);
} nesp_hal_t;

typedef struct {
    nesp_link_t *link;
    const nesp_hal_t *hal;
    char app[NESP_APP_ID];
    uint8_t app_version;
    uint8_t events[NESP_EVENT_QUEUE][2];
    uint8_t event_first;
    uint8_t event_count;
} nesp_sys_t;

typedef struct {
    const nesp_hal_t *hal;
    char name[NESP_NAME_MAX];
    uint8_t name_len;
    char password[NESP_PASSWORD_MAX];
    uint8_t password_len;
} nesp_net_t;

typedef struct {
    nesp_link_t *link;
} nesp_diag_t;

/* A Stick: the link and every service this firmware has. */
typedef struct {
    nesp_link_t link;
    nesp_sys_t sys;
    nesp_net_t net;
    nesp_diag_t diag;
    nesp_service_t services[3];
} nesp_stick_t;

void nesp_stick_init(nesp_stick_t *stick, const nesp_hal_t *hal);

/* Something for the console to hear of (NESP_EVENT_*): a button on the
 * Stick. Dropped if the queue is full. */
void nesp_stick_event(nesp_stick_t *stick, uint8_t code, uint8_t arg);

void nesp_sys_service(nesp_service_t *service, nesp_sys_t *sys, nesp_link_t *link,
                      const nesp_hal_t *hal);
void nesp_net_service(nesp_service_t *service, nesp_net_t *net, const nesp_hal_t *hal);
void nesp_diag_service(nesp_service_t *service, nesp_diag_t *diag, nesp_link_t *link);

#ifdef __cplusplus
}
#endif

#endif
