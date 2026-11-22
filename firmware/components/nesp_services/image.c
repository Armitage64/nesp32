/* A picture's file, JPEG or PNG, decoded to RGB (stb_image, in
 * third_party/stb), in memory from the hal: a board's PSRAM where it has
 * some. Called from one task at a time, the fetch's. */
#include <limits.h>
#include <string.h>

#include "nesp_services.h"

#define PIXELS_MAX (2048u * 2048u)  /* a thumbnail is a few hundred on a side */

static const nesp_hal_t *image_hal;

static void *image_alloc(size_t size)
{
    return image_hal->alloc(image_hal->ctx, size != 0 ? size : 1);
}

static void image_free(void *memory)
{
    if (memory != NULL) {
        image_hal->release(image_hal->ctx, memory);
    }
}

static void *image_realloc(void *memory, size_t old, size_t size)
{
    void *grown = image_alloc(size);
    if (grown != NULL && memory != NULL) {
        memcpy(grown, memory, old < size ? old : size);
    }
    image_free(memory);
    return grown;
}

#define STBI_MALLOC(size) image_alloc(size)
#define STBI_FREE(memory) image_free(memory)
#define STBI_REALLOC_SIZED(memory, old, size) image_realloc(memory, old, size)
#define STBI_ASSERT(x) ((void)0)
#define STBI_NO_STDIO
#define STBI_ONLY_JPEG
#define STBI_ONLY_PNG
#define STBI_NO_LINEAR
#define STBI_NO_HDR
#define STBI_NO_FAILURE_STRINGS
#define STBI_NO_THREAD_LOCALS
#define STBI_MAX_DIMENSIONS 8192
#define STB_IMAGE_IMPLEMENTATION

/* It is someone else's code, written to other warnings than these. */
#if defined(__clang__)
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Weverything"
#elif defined(__GNUC__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wconversion"
#pragma GCC diagnostic ignored "-Wsign-conversion"
#pragma GCC diagnostic ignored "-Wshadow"
#pragma GCC diagnostic ignored "-Wunused-function"
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wunused-but-set-variable"
#pragma GCC diagnostic ignored "-Wsign-compare"
#pragma GCC diagnostic ignored "-Wimplicit-fallthrough"
#pragma GCC diagnostic ignored "-Wmaybe-uninitialized"
#pragma GCC diagnostic ignored "-Wtype-limits"
#pragma GCC diagnostic ignored "-Wmisleading-indentation"
#pragma GCC diagnostic ignored "-Wdouble-promotion"
#pragma GCC diagnostic ignored "-Wcast-qual"
#pragma GCC diagnostic ignored "-Wstrict-prototypes"
#endif
#include "stb_image.h"
#if defined(__clang__)
#pragma clang diagnostic pop
#elif defined(__GNUC__)
#pragma GCC diagnostic pop
#endif

uint8_t *nesp_picture_decode(const nesp_hal_t *hal, const uint8_t *data, size_t len,
                             uint32_t *width, uint32_t *height)
{
    int w = 0;
    int h = 0;
    int channels = 0;
    image_hal = hal;                /* stbi_info has memory too */
    if (len == 0 || len > INT_MAX
        || !stbi_info_from_memory(data, (int)len, &w, &h, &channels)
        || w <= 0 || h <= 0 || (uint32_t)w * (uint32_t)h > PIXELS_MAX) {
        return NULL;
    }
    image_hal = hal;
    uint8_t *rgb = stbi_load_from_memory(data, (int)len, &w, &h, &channels, 3);
    if (rgb == NULL) {
        return NULL;
    }
    *width = (uint32_t)w;
    *height = (uint32_t)h;
    return rgb;
}

void nesp_picture_release(const nesp_hal_t *hal, uint8_t *rgb)
{
    image_hal = hal;
    stbi_image_free(rgb);
}
