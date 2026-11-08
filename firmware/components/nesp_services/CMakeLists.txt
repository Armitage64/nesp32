idf_component_register(SRCS "sys.c" "net.c" "diag.c" "wiki.c" "text.c" "raw.c" "juke.c" "peer.c" "arq.c" "stun.c" "vgm.c" "radar.c" "mp3.c" "resample.c" "tuner.c" "news.c" "weather.c" "bsky.c" "kbd.c" "http.c" "tape.c"
                       INCLUDE_DIRS "include" "../../../third_party/minimp3"
                       REQUIRES nesp_core)
# The version (nesp_version.h), from VERSION and the commit, on every build:
# tagging a commit makes it the release without changing a file here. The
# header is rewritten only if what it says changed.
if(NOT CMAKE_BUILD_EARLY_EXPANSION)
    idf_build_get_property(python PYTHON)
    set(version_h "${CMAKE_CURRENT_BINARY_DIR}/nesp_version.h")
    add_custom_target(nesp_version
                      COMMAND ${python} "${CMAKE_CURRENT_LIST_DIR}/../../../tools/version.py"
                              header "${version_h}"
                      BYPRODUCTS "${version_h}")
    add_dependencies(${COMPONENT_LIB} nesp_version)
    target_include_directories(${COMPONENT_LIB} PUBLIC "${CMAKE_CURRENT_BINARY_DIR}")
endif()
