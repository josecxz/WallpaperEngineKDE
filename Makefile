ID      := org.jose.wallpaperengine
DEST    := $(HOME)/.local/share/plasma/wallpapers/$(ID)
SRC     := $(CURDIR)/plugin

# El modulo QML en C++. Se instala aparte del paquete del wallpaper porque el
# motor de QML lo busca en su ruta de imports, no dentro del KPackage.
QMLMOD  := $(HOME)/.local/lib/qt6/qml
QMLDEST := $(QMLMOD)/org/jose/wallpaperengine/render
LIB     := libwallpaperenginerender.so

# environment.d lo lee el gestor de usuario de systemd al iniciar sesion, y
# plasmashell hereda de ahi. Es la unica forma de que la ruta de imports
# sobreviva a un reinicio.
ENVDIR  := $(if $(XDG_CONFIG_HOME),$(XDG_CONFIG_HOME),$(HOME)/.config)/environment.d
ENVFILE := $(ENVDIR)/50-wallpaperengine.conf

QT_MODULES := Qt6Quick Qt6Qml Qt6Gui Qt6Core
# Las cabeceras de QRhi viven en una ruta versionada: es API semipublica, sin
# garantia de compatibilidad entre versiones menores de Qt.
QT_VER  := $(shell pkg-config --modversion Qt6Core)
PRIVINC := -I/usr/include/qt6/QtGui/$(QT_VER) -I/usr/include/qt6/QtGui/$(QT_VER)/QtGui

# -MMD -MP genera las dependencias de cabecera automaticamente. Declararlas a
# mano era incompleto: moc_sceneview.o no dependia de glexecutor.h aunque lo
# incluye via sceneview.h, asi que una compilacion incremental podia enlazar
# objetos que veian layouts distintos de la misma clase. Eso produce fallos que
# no se reproducen tras un `make clean`, que es justo lo que paso.
CXXFLAGS := -O2 -fPIC -std=c++20 -Wall -Wextra -Wno-unused-parameter -MMD -MP \
            $(shell pkg-config --cflags $(QT_MODULES)) $(PRIVINC)
# -z nodelete: la biblioteca no se descarga nunca. Es buena practica en un
# plugin de QML -- el motor puede descargarlo con objetos aun vivos -- pero que
# quede claro: NO fue lo que arreglo los SIGBUS. La causa era instalar con `cp`
# sobre la .so mapeada (ver install-qml).
LDFLAGS  := -shared -Wl,-z,nodelete
LDLIBS   := $(shell pkg-config --libs $(QT_MODULES)) -lGL

MOC     := /usr/lib/qt6/moc
BUILD   := obj
OBJS    := $(BUILD)/glexecutor.o $(BUILD)/sceneview.o $(BUILD)/plugin.o \
           $(BUILD)/moc_sceneview.o

.PHONY: all build install install-qml install-package install-env uninstall \
        reload status clean plan

all: build

# ── modulo QML en C++ ───────────────────────────────────────────────────────
build: $(BUILD)/$(LIB)

$(BUILD):
	@mkdir -p $(BUILD)

$(BUILD)/moc_sceneview.cpp: src/sceneview.h | $(BUILD)
	$(MOC) $(shell pkg-config --cflags-only-I $(QT_MODULES)) $< -o $@

# plugin.cpp declara su QObject en el propio .cpp, asi que su moc se incluye.
$(BUILD)/plugin.moc: src/plugin.cpp | $(BUILD)
	$(MOC) $(shell pkg-config --cflags-only-I $(QT_MODULES)) $< -o $@

$(BUILD)/%.o: src/%.cpp | $(BUILD)
	$(CXX) $(CXXFLAGS) -I$(BUILD) -Isrc -c $< -o $@

$(BUILD)/moc_sceneview.o: $(BUILD)/moc_sceneview.cpp | $(BUILD)
	$(CXX) $(CXXFLAGS) -Isrc -c $< -o $@

# plugin.cpp incluye su propio .moc, que no puede deducirse de los includes.
$(BUILD)/plugin.o: $(BUILD)/plugin.moc

-include $(OBJS:.o=.d)

$(BUILD)/$(LIB): $(OBJS)
	$(CXX) $(LDFLAGS) -o $@ $(OBJS) $(LDLIBS)
	@echo "construido: $@"

# ── instalacion ─────────────────────────────────────────────────────────────
install: install-qml install-package install-env

# Instalar con rename atomico, NO con cp. `cp` trunca y reescribe el mismo
# inodo, y plasmashell tiene esa biblioteca mapeada en memoria: sus paginas de
# codigo quedan invalidas y el proceso muere con SIGBUS/BUS_ADRERR en cuanto
# vuelve a ejecutar cualquier cosa de la .so. `mv` crea una entrada nueva y
# deja el inodo viejo vivo mientras alguien lo tenga mapeado.
install-qml: build
	@mkdir -p $(QMLDEST)
	@cp $(BUILD)/$(LIB) $(QMLDEST)/$(LIB).new && mv -f $(QMLDEST)/$(LIB).new $(QMLDEST)/$(LIB)
	@cp src/qmldir $(QMLDEST)/qmldir.new && mv -f $(QMLDEST)/qmldir.new $(QMLDEST)/qmldir
	@echo "modulo QML  -> $(QMLDEST)"

install-package:
	@mkdir -p $(dir $(DEST))
	@ln -sfn $(SRC) $(DEST)
	@echo "paquete     -> $(DEST) -> $(SRC)"

# Qt no escanea ~/.local/lib/qt6/qml, asi que sin esta variable plasmashell
# carga el fondo, falla el import y se queda sin nada. Antes se ponia solo con
# `systemctl --user set-environment`, que vive en la sesion: al reiniciar la
# maquina se perdia y el fondo desaparecia sin dejar mas rastro que un
# "module ... is not installed" en el journal.
#
# La forma ${VAR:+:${VAR}} de systemd anade la ruta a un QML_IMPORT_PATH que ya
# exista y no deja un separador suelto cuando no lo hay.
install-env:
	@mkdir -p $(ENVDIR)
	@printf '%s\n' \
		'# Generado por `make install-env` de WallpaperEngine. No editar a mano.' \
		'# Lo lee el gestor de usuario de systemd al iniciar sesion; plasmashell' \
		'# hereda de ahi y asi encuentra el modulo QML del motor tras reiniciar.' \
		'QML_IMPORT_PATH=$(QMLMOD)$${QML_IMPORT_PATH:+:$${QML_IMPORT_PATH}}' \
		> $(ENVFILE).new && mv -f $(ENVFILE).new $(ENVFILE)
	@echo "entorno     -> $(ENVFILE)"
	@echo "aplica a la sesion en curso con: make reload"

uninstall:
	@rm -f $(DEST)
	@rm -rf $(QMLDEST)
	@rm -f $(ENVFILE)
	@echo "desinstalado (cierra sesion para soltar QML_IMPORT_PATH)"

# install-env deja la variable puesta para los proximos inicios de sesion, pero
# el gestor de usuario ya arrancado no relee environment.d: se la inyectamos
# tambien aqui para no tener que cerrar sesion.
reload: install-env
	@systemctl --user set-environment QML_IMPORT_PATH=$(QMLMOD)
	@systemctl --user restart plasma-plasmashell.service \
		|| (kquitapp6 plasmashell && sleep 2 && kstart plasmashell)
	@echo "plasmashell reiniciado con QML_IMPORT_PATH=$(QMLMOD)"

# ── plan de render ──────────────────────────────────────────────────────────
# Ruta del wallpaper a renderizar. Sin valor por defecto: depende de a que se
# haya suscrito cada uno. `tools/wepaths.py` localiza la biblioteca de Steam.
WALLPAPER ?=

plan:
	@test -n "$(WALLPAPER)" || { \
		echo "uso: make plan WALLPAPER=<ruta al wallpaper>"; \
		echo "wallpapers disponibles:"; \
		python3 -c 'import sys; sys.path.insert(0,"tools"); import wepaths; \
			print("\n".join(f"  {d}" for d in sorted(wepaths.we_workshop().iterdir()) \
			if (d/"scene.pkg").is_file()))' 2>/dev/null \
			|| echo "  (define WE_WORKSHOP; ver tools/wepaths.py)"; \
		exit 1; }
	@mkdir -p $(SRC)/contents/scene
	python3 tools/werender.py $(WALLPAPER) --emit-plan $(SRC)/contents/scene
	@echo "plan -> $(SRC)/contents/scene/plan.txt"

status:
	@echo "== paquete =="; ls -la $(DEST) 2>/dev/null || echo "no instalado"
	@echo "== modulo QML =="; ls -la $(QMLDEST) 2>/dev/null || echo "no instalado"
	@echo "== entorno persistente =="; \
		cat $(ENVFILE) 2>/dev/null || echo "$(ENVFILE) no existe"
	@echo "== entorno de plasmashell =="; \
		tr '\0' '\n' < /proc/$$(pgrep -x plasmashell | head -1)/environ 2>/dev/null \
		| grep QML_IMPORT_PATH || echo "QML_IMPORT_PATH sin definir"
	@echo "== plugin por containment =="; \
		grep -c 'wallpaperplugin=$(ID)$$' \
			$(HOME)/.config/plasma-org.kde.plasma.desktop-appletsrc 2>/dev/null \
			| xargs -I{} echo "{} usan $(ID)"; \
		grep 'wallpaperplugin=' \
			$(HOME)/.config/plasma-org.kde.plasma.desktop-appletsrc 2>/dev/null \
			| sort | uniq -c

clean:
	@rm -rf $(BUILD)
	@echo "limpio"
