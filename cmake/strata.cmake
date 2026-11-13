# strata - CMake integration (see ADR-0009)
#
#   strata_add_project(SCHEMA <dir> PRESETS <dir> COMPONENTS <dir> PRESET <name>
#                      [OUT <dir>])
#   strata_add_component(<name> [LAYER <layer>])
#   strata_link_resolves(<target> <component>...)
#   strata_get_feature(<id> <out-var>)
#   strata_get_config(<id> <out-var>)

if(NOT DEFINED STRATA_PYTHON)
  set(STRATA_PYTHON "python" CACHE FILEPATH "Python interpreter used to run strata")
endif()

# A macro, not a function: the generated .cmake must be included in the scope of
# the calling CMakeLists.txt, so that STRATA_FEATURE_* / STRATA_CONFIG_* stay
# visible to strata_get_feature()/strata_get_config() across include().
macro(strata_add_project)
  cmake_parse_arguments(_STRATA "" "SCHEMA;PRESETS;COMPONENTS;PRESET;OUT" "" ${ARGN})

  foreach(_strata_required SCHEMA PRESETS COMPONENTS PRESET)
    if(NOT _STRATA_${_strata_required})
      message(FATAL_ERROR
              "strata_add_project: missing ${_strata_required}")
    endif()
  endforeach()

  set(_strata_out "${_STRATA_OUT}")
  if(NOT _strata_out)
    set(_strata_out "${CMAKE_BINARY_DIR}/generated")
  endif()

  file(GLOB _strata_schema_files "${_STRATA_SCHEMA}/*.toml")
  file(GLOB _strata_preset_file "${_STRATA_PRESETS}/${_STRATA_PRESET}.toml")
  file(GLOB_RECURSE _strata_component_files "${_STRATA_COMPONENTS}/*/strata_features.*")

  execute_process(
    COMMAND "${STRATA_PYTHON}" -m strata generate
            --schema     "${_STRATA_SCHEMA}"
            --presets    "${_STRATA_PRESETS}"
            --components "${_STRATA_COMPONENTS}"
            --preset     "${_STRATA_PRESET}"
            --out        "${_strata_out}"
    WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
    RESULT_VARIABLE _strata_rc)

  if(_strata_rc)
    message(FATAL_ERROR "strata: generation failed (see the messages above).")
  endif()

  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
               ${_strata_schema_files} ${_strata_preset_file} ${_strata_component_files})

  set(STRATA_OUT "${_strata_out}")
  set(STRATA_PRESET_NAME "${_STRATA_PRESET}")
  include("${_strata_out}/strata_features.cmake")
  include("${_strata_out}/config/strata_config.cmake")
endmacro()

function(strata_add_component name)
  cmake_parse_arguments(_STRATA "" "LAYER" "" ${ARGN})
  if(NOT STRATA_OUT)
    message(FATAL_ERROR "strata_add_component: call strata_add_project() first")
  endif()
  if(NOT _STRATA_LAYER)
    set(_STRATA_LAYER "${name}")
  endif()
  add_library(strata::${name} INTERFACE IMPORTED)
  set_target_properties(strata::${name} PROPERTIES
    INTERFACE_INCLUDE_DIRECTORIES "${STRATA_OUT}/${_STRATA_LAYER}")
endfunction()

function(strata_link_resolves target)
  foreach(component IN LISTS ARGN)
    if(NOT TARGET strata::${component})
      message(FATAL_ERROR
              "strata_link_resolves: unknown component \"${component}\"")
    endif()
    target_link_libraries(${target} PRIVATE strata::${component})
  endforeach()
endfunction()

function(strata_get_feature id out)
  if(NOT DEFINED STRATA_FEATURE_${id})
    message(FATAL_ERROR "strata_get_feature: unknown feature \"${id}\"")
  endif()
  set(${out} "${STRATA_FEATURE_${id}}" PARENT_SCOPE)
endfunction()

function(strata_get_config id out)
  if(NOT DEFINED STRATA_CONFIG_${id})
    message(FATAL_ERROR "strata_get_config: unknown config variable \"${id}\"")
  endif()
  set(${out} "${STRATA_CONFIG_${id}}" PARENT_SCOPE)
endfunction()
