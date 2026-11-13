# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CYK-Dot
#
# strata - CMake integration.
#
#   strata_add_project(SCHEMA <dir> PRESETS <dir> [OUT <dir>])
#   strata_add_component(<name> <directory>)
#   strata_link_resolves(<target> <component>...)
#   strata_get_feature(<id> <out-var>)
#   strata_get_config(<id> <out-var>)
#
# The product is chosen when configuring, not in this file:
#
#   cmake -B build/plb -DSTRATA_PRESET=daplink_plb
#
# so one CMakeLists.txt builds every product.

if(NOT DEFINED STRATA_PYTHON)
  set(STRATA_PYTHON "python" CACHE FILEPATH "Python interpreter used to run strata")
endif()


macro(strata_add_project)
  cmake_parse_arguments(_STRATA "" "SCHEMA;PRESETS;OUT;PRESET" "" ${ARGN})

  if(NOT _STRATA_SCHEMA OR NOT _STRATA_PRESETS)
    message(FATAL_ERROR "strata_add_project: SCHEMA and PRESETS are required")
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
  set_property(GLOBAL PROPERTY STRATA_COMPONENT_SPECS "")
  set(STRATA_GENERATED FALSE CACHE INTERNAL "strata: generation done")
endmacro()


function(strata_add_component name)
  if(ARGC LESS 2)
    message(FATAL_ERROR
            "strata_add_component: give the component directory as the second argument")
  endif()
  if(ARGC GREATER 2)
    message(FATAL_ERROR "strata_add_component: expected <name> <directory>, got ${ARGN}")
  endif()
  set_property(GLOBAL APPEND PROPERTY STRATA_COMPONENT_SPECS "${name}=${ARGV1}")
endfunction()


# Generation is deferred until something needs the values, because components are
# declared after strata_add_project(). Every consumer includes the generated files
# in its own scope, so the values are visible wherever they are read.
macro(_strata_ensure)
  if(NOT STRATA_GENERATED)
    if(NOT STRATA_SCHEMA_DIR)
      message(FATAL_ERROR "strata: call strata_add_project() before anything else")
    endif()

    get_property(_strata_specs GLOBAL PROPERTY STRATA_COMPONENT_SPECS)
    if(NOT _strata_specs)
      message(FATAL_ERROR
              "strata: no components declared.\n"
              "Call strata_add_component(<name> <directory>) for each one.")
    endif()

    set(_strata_args "")
    foreach(_strata_spec IN LISTS _strata_specs)
      list(APPEND _strata_args --component "${_strata_spec}")
    endforeach()

    execute_process(
      COMMAND "${STRATA_PYTHON}" -m strata generate
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

    _strata_declare_targets("${_strata_specs}")
    _strata_watch_inputs("${_strata_specs}")
    set(STRATA_GENERATED TRUE CACHE INTERNAL "strata: generation done")
  endif()

  include("${STRATA_OUT_DIR}/strata_features.cmake")
  include("${STRATA_OUT_DIR}/config/strata_config.cmake")
endmacro()


function(_strata_declare_targets specs)
  file(READ "${STRATA_OUT_DIR}/strata_manifest.json" _manifest)
  foreach(spec IN LISTS specs)
    string(FIND "${spec}" "=" _eq)
    string(SUBSTRING "${spec}" 0 ${_eq} _name)
    string(JSON _layer GET "${_manifest}" components "${_name}" layer)
    add_library(strata::${_name} INTERFACE IMPORTED)
    set_target_properties(strata::${_name} PROPERTIES
      INTERFACE_INCLUDE_DIRECTORIES "${STRATA_OUT_DIR}/${_layer}")
  endforeach()
endfunction()


function(_strata_watch_inputs specs)
  file(GLOB _inputs "${STRATA_SCHEMA_DIR}/*.toml" "${STRATA_PRESETS_DIR}/${STRATA_PRESET}.toml")
  foreach(spec IN LISTS specs)
    string(FIND "${spec}" "=" _eq)
    string(SUBSTRING "${spec}" ${_eq} -1 _rest)
    string(SUBSTRING "${_rest}" 1 -1 _dir)
    file(GLOB_RECURSE _component_files "${_dir}/strata_features.*")
    list(APPEND _inputs ${_component_files})
  endforeach()
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${_inputs})
endfunction()


macro(strata_link_resolves target)
  set(_strata_wanted ${ARGN})
  _strata_ensure()
  foreach(_strata_component IN LISTS _strata_wanted)
    if(NOT TARGET strata::${_strata_component})
      message(FATAL_ERROR
              "strata_link_resolves: unknown component \"${_strata_component}\"")
    endif()
    target_link_libraries(${target} PRIVATE strata::${_strata_component})
  endforeach()
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
