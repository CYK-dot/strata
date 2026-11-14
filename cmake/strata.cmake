# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot
#
# strata - CMake integration.
#
#   strata_project(SCHEMA <dir> PRESETS <dir> [OUT <dir>])
#   strata_add_component_path(<directory>)
#   strata_link_resolves(<target>)
#   strata_get_feature(<id> <out-var>)
#   strata_get_config(<id> <out-var>)
#
# The component's identity is not the directory's: the top-level
# `component = "ctl"` line in its strata_features.toml names it, and the
# top-level `requires` line names the components it reads from.
#
# The product is chosen when configuring, not in this file:
#
#   cmake -B build/plb -DSTRATA_PRESET=daplink_plb
#
# so one CMakeLists.txt builds every product.

if(NOT DEFINED STRATA_PYTHON)
  set(STRATA_PYTHON "python" CACHE FILEPATH "Python interpreter used to run strata")
endif()

# The strata package lives next to this cmake/ directory. Its parent goes on
# PYTHONPATH for the generate step, so the invocation does not depend on where
# the package sits relative to CMAKE_SOURCE_DIR.
get_filename_component(_STRATA_PACKAGE_PARENT "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)


macro(strata_project)
  cmake_parse_arguments(_STRATA "" "SCHEMA;PRESETS;OUT" "" ${ARGN})

  if(_STRATA_UNPARSED_ARGUMENTS)
    message(FATAL_ERROR
            "strata_project: unexpected arguments: ${_STRATA_UNPARSED_ARGUMENTS}\n"
            "The preset is not an argument; configure with -DSTRATA_PRESET=<name>.")
  endif()

  if(NOT _STRATA_SCHEMA OR NOT _STRATA_PRESETS)
    message(FATAL_ERROR "strata_project: SCHEMA and PRESETS are required")
  endif()

  if(_STRATA_PRESET)
    set(STRATA_PRESET "${_STRATA_PRESET}" CACHE STRING "Product to build" FORCE)
  endif()
  set(STRATA_PRESET "${STRATA_PRESET}" CACHE STRING "Product to build")
  if(NOT STRATA_PRESET)
    message(FATAL_ERROR
            "strata: no preset selected.\n"
            "Configure with -DSTRATA_PRESET=<name>, or set it in a CMake preset.")
  endif()

  set(_strata_out "${_STRATA_OUT}")
  if(NOT _strata_out)
    set(_strata_out "${CMAKE_BINARY_DIR}/generated")
  endif()

  set(STRATA_SCHEMA_DIR  "${_STRATA_SCHEMA}"  CACHE INTERNAL "strata: schema directory")
  set(STRATA_PRESETS_DIR "${_STRATA_PRESETS}" CACHE INTERNAL "strata: presets directory")
  set(STRATA_OUT_DIR     "${_strata_out}"     CACHE INTERNAL "strata: output directory")
  set_property(GLOBAL PROPERTY STRATA_COMPONENT_DIRS "")
  set(STRATA_GENERATED FALSE CACHE INTERNAL "strata: generation done")
endmacro()


function(strata_add_component_path directory)
  if(ARGC GREATER 1)
    message(FATAL_ERROR "strata_add_component_path: expected one <directory>, got ${ARGN}")
  endif()
  if(NOT STRATA_SCHEMA_DIR)
    message(FATAL_ERROR
            "strata_add_component_path: call strata_project() before adding components.")
  endif()
  if(STRATA_GENERATED)
    message(FATAL_ERROR
            "strata_add_component_path: too late; the feature graph has already been generated.\n"
            "Move every strata_add_component_path above the first consumer.")
  endif()
  set_property(GLOBAL APPEND PROPERTY STRATA_COMPONENT_DIRS "${directory}")
endfunction()


# Generation is deferred until something needs the values, because components
# are declared after strata_project(). All strata_add_component_path() calls
# must come before the first consumer; generation runs once, with whatever the
# graph holds at that point. _strata_ensure is a macro so the generated .cmake
# lands in the caller's scope, where the values are then read.
macro(_strata_ensure)
  if(NOT STRATA_GENERATED)
    if(NOT STRATA_SCHEMA_DIR)
      message(FATAL_ERROR "strata: call strata_project() before anything else")
    endif()

    get_property(_strata_dirs GLOBAL PROPERTY STRATA_COMPONENT_DIRS)
    if(NOT _strata_dirs)
      message(FATAL_ERROR
              "strata: no components declared.\n"
              "Call strata_add_component_path(<directory>) for each one.")
    endif()

    set(_strata_args "")
    foreach(_strata_dir IN LISTS _strata_dirs)
      list(APPEND _strata_args --component "${_strata_dir}")
    endforeach()

    set(_strata_pythonpath "${_STRATA_PACKAGE_PARENT}")
    if(DEFINED ENV{PYTHONPATH} AND NOT "$ENV{PYTHONPATH}" STREQUAL "")
      if(WIN32)
        set(_strata_sep ";")
      else()
        set(_strata_sep ":")
      endif()
      string(APPEND _strata_pythonpath "${_strata_sep}$ENV{PYTHONPATH}")
    endif()

    execute_process(
      COMMAND "${CMAKE_COMMAND}" -E env
              "PYTHONPATH=${_strata_pythonpath}"
              "${STRATA_PYTHON}" -m strata generate
              --schema  "${STRATA_SCHEMA_DIR}"
              --presets "${STRATA_PRESETS_DIR}"
              ${_strata_args}
              --preset  "${STRATA_PRESET}"
              --out     "${STRATA_OUT_DIR}"
      WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
      RESULT_VARIABLE _strata_rc)

    if(_strata_rc)
      message(FATAL_ERROR "strata: generation failed (see the messages above).")
    endif()

    _strata_watch_inputs("${_strata_dirs}")
    set(STRATA_GENERATED TRUE CACHE INTERNAL "strata: generation done")
  endif()

  include("${STRATA_OUT_DIR}/strata_features.cmake")
  include("${STRATA_OUT_DIR}/config/strata_config.cmake")
endmacro()


function(_strata_watch_inputs dirs)
  file(GLOB _inputs "${STRATA_SCHEMA_DIR}/*.toml" "${STRATA_PRESETS_DIR}/${STRATA_PRESET}.toml")
  foreach(_dir IN LISTS dirs)
    file(GLOB_RECURSE _component_files "${_dir}/strata_features.*")
    list(APPEND _inputs ${_component_files})
  endforeach()
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${_inputs})
endfunction()


# Features are global: every target that subscribes sees all of them.
macro(strata_link_resolves target)
  set(_strata_subscriber ${target})
  _strata_ensure()
  target_include_directories(${_strata_subscriber} PRIVATE "${STRATA_OUT_DIR}")
endmacro()


macro(strata_get_feature id out)
  _strata_ensure()
  if(NOT DEFINED STRATA_FEATURE_${id})
    message(FATAL_ERROR "strata_get_feature: unknown feature \"${id}\"")
  endif()
  set(${out} "${STRATA_FEATURE_${id}}")
endmacro()


macro(strata_get_config id out)
  _strata_ensure()
  if(NOT DEFINED STRATA_CONFIG_${id})
    message(FATAL_ERROR "strata_get_config: unknown configuration item \"${id}\"")
  endif()
  set(${out} "${STRATA_CONFIG_${id}}")
endmacro()
