from pathlib import Path
import sys
import time


# Calcula l'arrel del projecte per poder trobar la llibreria local.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Ruta del repositori on hi ha el paquet sem6000.
LIBRARY_ROOT = PROJECT_ROOT / "github2" / "python3-voltcraft-sem6000"
DEVICE_ADDRESS = "b3:00:00:00:30:43"

# Afegeix la llibreria al path d'importacio si encara no hi es.
if str(LIBRARY_ROOT) not in sys.path:
    sys.path.insert(0, str(LIBRARY_ROOT))

# Importa el modul principal de la llibreria un cop la ruta ja es visible.
try:
    from sem6000 import sem6000
except ModuleNotFoundError as exc:
    if exc.name == "bluepy":
        requirements_path = LIBRARY_ROOT / "requirements.txt"
        venv_path = PROJECT_ROOT / ".venv"
        raise SystemExit(
            "Falta la dependencia 'bluepy'. Crea un entorn virtual i installa les dependencies amb:\n"
            f"python3 -m venv {venv_path}\n"
            f"source {venv_path}/bin/activate\n"
            f"python -m pip install -r {requirements_path}"
        ) from exc
    raise


def discover_devices():
    """Retorna els dispositius SEM6000 visibles per Bluetooth."""
    # Fa un escaneig Bluetooth i retorna la llista de dispositius compatibles.
    return sem6000.SEM6000.discover()


def connect_device(address, pin="0000", debug=False):
    """Crea una connexio amb un dispositiu SEM6000."""
    # Crea l'objecte de connexio i, si hi ha PIN, intenta autoritzar-se.
    return sem6000.SEM6000(address, pin=pin, debug=debug)


def read_power_in_watt(device):
    """Llegeix la potencia instantania en watts."""
    # El dispositiu retorna la potencia en milliwatts; es converteix a watts.
    measurement = device.request_measurement()
    return measurement.power_in_milliwatt / 1000


def main():
    # Es connecta directament a l'adreca configurada.
    print(f"Connectant a {DEVICE_ADDRESS}...")

    device = connect_device(DEVICE_ADDRESS)
    should_power_off = False

    try:
        device.power_on()
        should_power_off = True
        print("Endoll ences. Premeu Ctrl+C per aturar el monitoratge.")

        while True:
            power_in_watt = read_power_in_watt(device)
            print(f"Potencia: {power_in_watt:.3f} W")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nMonitoratge aturat.")
    finally:
        if should_power_off:
            try:
                print("Apagant endoll...")
                device.power_off()
            except Exception as exc:
                print(f"No s'ha pogut apagar l'endoll: {exc}")
        device.disconnect()


if __name__ == "__main__":
    # Punt d'entrada quan el fitxer s'executa directament.
    main()
