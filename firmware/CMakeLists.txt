# The Stick's firmware: ESP-IDF 5.x, with M5Unified for the screen, the
# buttons and the power.
#
#   idf.py set-target esp32      a StickC Plus2
#   idf.py set-target esp32s3    a StickS3
#   idf.py build flash monitor
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(nesp32)
