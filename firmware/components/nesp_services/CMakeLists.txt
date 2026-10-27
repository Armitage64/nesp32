idf_component_register(SRCS "sys.c" "net.c" "diag.c" "wiki.c" "text.c" "raw.c" "juke.c" "peer.c" "arq.c" "stun.c" "vgm.c" "radar.c" "mp3.c" "tuner.c" "news.c" "weather.c" "bsky.c" "kbd.c"
                       INCLUDE_DIRS "include" "../../../third_party/minimp3"
                       REQUIRES nesp_core)
