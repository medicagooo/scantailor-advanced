set(CMAKE_AUTORCC ON)
add_executable(scantailor-cli main.cpp BatchRunner.cpp BatchRunner.h
    "${SCANTAILOR_RESOURCES_DIR}/resources.qrc"
    "${SCANTAILOR_RESOURCES_DIR}/dark_scheme/dark_scheme.qrc"
    "${SCANTAILOR_RESOURCES_DIR}/light_scheme/light_scheme.qrc")
target_link_libraries(scantailor-cli PRIVATE core ${EXTRA_LIBS})
target_include_directories(scantailor-cli PRIVATE "$<TARGET_PROPERTY:TIFF::TIFF,INTERFACE_INCLUDE_DIRECTORIES>")
install(TARGETS scantailor-cli RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
if(Qt6_FOUND AND WIN32)
  add_custom_command(TARGET scantailor-cli POST_BUILD
    COMMAND "${QT_BINDIR}/windeployqt" $<TARGET_FILE:scantailor-cli>
    COMMAND ${CMAKE_COMMAND} -E make_directory "$<TARGET_FILE_DIR:scantailor-cli>/platforms"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different "$<TARGET_FILE:Qt6::QOffscreenIntegrationPlugin>"
        "$<TARGET_FILE_DIR:scantailor-cli>/platforms/")
  install(FILES "$<TARGET_FILE:Qt6::QOffscreenIntegrationPlugin>"
      DESTINATION "${CMAKE_INSTALL_BINDIR}/platforms")
endif()
