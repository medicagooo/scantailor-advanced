set(CMAKE_AUTORCC ON)
add_executable(scantailor-cli main.cpp BatchRunner.cpp BatchRunner.h
    ProjectSession.cpp ProjectSession.h LegacyOptions.cpp MenuLauncher.cpp MenuLauncher.h
    "${SCANTAILOR_RESOURCES_DIR}/resources.qrc"
    "${SCANTAILOR_RESOURCES_DIR}/dark_scheme/dark_scheme.qrc"
    "${SCANTAILOR_RESOURCES_DIR}/light_scheme/light_scheme.qrc")
target_link_libraries(scantailor-cli PRIVATE core ${EXTRA_LIBS})
target_include_directories(scantailor-cli PRIVATE "$<TARGET_PROPERTY:TIFF::TIFF,INTERFACE_INCLUDE_DIRECTORIES>")
install(TARGETS scantailor-cli RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
# Relink/copy when the controller changes even without a C++ source edit.
set_property(TARGET scantailor-cli APPEND PROPERTY LINK_DEPENDS
    "${CMAKE_SOURCE_DIR}/scripts/menu.py"
    "${CMAKE_SOURCE_DIR}/scripts/process_pdf_folder.py"
    "${CMAKE_SOURCE_DIR}/scripts/scantailor_menu/__init__.py"
    "${CMAKE_SOURCE_DIR}/scripts/scantailor_menu/model.py"
    "${CMAKE_SOURCE_DIR}/scripts/scantailor_menu/console.py"
    "${CMAKE_SOURCE_DIR}/scripts/scantailor_menu/ui.py")
add_custom_command(TARGET scantailor-cli POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_SOURCE_DIR}/scripts/menu.py" "$<TARGET_FILE_DIR:scantailor-cli>/menu.py"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_SOURCE_DIR}/scripts/process_pdf_folder.py" "$<TARGET_FILE_DIR:scantailor-cli>/process_pdf_folder.py"
    COMMAND ${CMAKE_COMMAND} -E copy_directory "${CMAKE_SOURCE_DIR}/scripts/scantailor_menu" "$<TARGET_FILE_DIR:scantailor-cli>/scantailor_menu")
install(FILES "${CMAKE_SOURCE_DIR}/scripts/menu.py" "${CMAKE_SOURCE_DIR}/scripts/process_pdf_folder.py" DESTINATION "${CMAKE_INSTALL_BINDIR}")
install(DIRECTORY "${CMAKE_SOURCE_DIR}/scripts/scantailor_menu" DESTINATION "${CMAKE_INSTALL_BINDIR}" PATTERN "__pycache__" EXCLUDE)
if(Qt6_FOUND AND WIN32)
  add_custom_command(TARGET scantailor-cli POST_BUILD
    COMMAND "${QT_BINDIR}/windeployqt" $<TARGET_FILE:scantailor-cli>
    COMMAND ${CMAKE_COMMAND} -E make_directory "$<TARGET_FILE_DIR:scantailor-cli>/platforms"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different "$<TARGET_FILE:Qt6::QOffscreenIntegrationPlugin>"
        "$<TARGET_FILE_DIR:scantailor-cli>/platforms/")
  install(FILES "$<TARGET_FILE:Qt6::QOffscreenIntegrationPlugin>"
      DESTINATION "${CMAKE_INSTALL_BINDIR}/platforms")
endif()
