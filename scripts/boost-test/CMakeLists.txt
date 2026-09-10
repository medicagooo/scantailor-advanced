cmake_minimum_required(VERSION 3.16)
project(ScanTailorBoostTest LANGUAGES CXX)
set(BOOST_ROOT "" CACHE PATH "Extracted Boost 1.85.0 source")
if(NOT EXISTS "${BOOST_ROOT}/boost/version.hpp")
  message(FATAL_ERROR "BOOST_ROOT must contain the extracted Boost sources")
endif()
# Same UTF_SOURCES as Boost 1.85 libs/test/build/Jamfile.v2. This small
# offline CMake build avoids invoking bootstrap.bat or another shell on Windows.
set(sources compiler_log_formatter debug decorator execution_monitor framework
    plain_report_formatter progress_monitor results_collector results_reporter
    test_framework_init_observer test_tools test_tree unit_test_log unit_test_main
    unit_test_monitor unit_test_parameters junit_log_formatter xml_log_formatter xml_report_formatter)
list(TRANSFORM sources PREPEND "${BOOST_ROOT}/libs/test/src/")
list(TRANSFORM sources APPEND ".cpp")
add_library(boost_unit_test_framework STATIC ${sources})
target_include_directories(boost_unit_test_framework PRIVATE "${BOOST_ROOT}")
target_compile_features(boost_unit_test_framework PRIVATE cxx_std_17)
install(TARGETS boost_unit_test_framework ARCHIVE DESTINATION lib)
