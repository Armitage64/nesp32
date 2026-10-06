# The link, less the hardware. nesp_proto.h is written from proto/nesp.toml
# when the firmware is built, as the Makefile writes it for the tests.
idf_component_register(SRCS "nesp_core.c" INCLUDE_DIRS "include")

set(NESP_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../..")
set(NESP_GEN "${CMAKE_CURRENT_BINARY_DIR}/gen")
file(MAKE_DIRECTORY "${NESP_GEN}")
target_include_directories(${COMPONENT_LIB} PUBLIC "${NESP_GEN}")
add_custom_command(
    OUTPUT "${NESP_GEN}/nesp_proto.h"
    COMMAND ${PYTHON} "${NESP_ROOT}/tools/gen_proto.py" "${NESP_GEN}"
    DEPENDS "${NESP_ROOT}/proto/nesp.toml" "${NESP_ROOT}/tools/gen_proto.py"
    COMMENT "nesp_proto.h from proto/nesp.toml")
add_custom_target(nesp_proto DEPENDS "${NESP_GEN}/nesp_proto.h")
add_dependencies(${COMPONENT_LIB} nesp_proto)
