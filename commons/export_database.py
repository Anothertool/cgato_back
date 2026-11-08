import argparse
import os
import subprocess
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

from psycopg.conninfo import conninfo_to_dict, make_conninfo


"""
cd /app
python -m commons.export_database
El comando genera el .dump en /tmp e imprime su ruta. Para bajarlo a tu equipo, abre una terminal local y ejecuta lo siguiente con el ID de instancia del servicio y la ruta que imprimió Python:
scp ID_INSTANCIA@ssh.railway.com:/tmp/cgato-EJEMPLO.dump .
"""


def export_database(output: BinaryIO) -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("Falta DATABASE_URL en el entorno del backend.")

    connection = conninfo_to_dict(database_url)
    password = connection.pop("password", None)
    environment = os.environ.copy()
    if password is not None:
        environment["PGPASSWORD"] = password

    subprocess.run(
        ["pg_dump", "--format=custom", "--no-password", "--dbname", make_conninfo(**connection)],
        env=environment,
        stdout=output,
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Exporta PostgreSQL usando DATABASE_URL.")
    parser.add_argument("--stdout", action="store_true", help="Envía el volcado binario a stdout.")
    args = parser.parse_args()

    try:
        if args.stdout:
            if sys.stdout.isatty():
                parser.error("--stdout requiere redirección a un archivo o SSH sin terminal (-T).")
            export_database(sys.stdout.buffer)
            return

        with NamedTemporaryFile(prefix="cgato-", suffix=".dump", dir="/tmp", delete=False) as output:
            path = Path(output.name)
            try:
                export_database(output)
            except BaseException:
                path.unlink()
                raise
        print(path)
    except FileNotFoundError:
        raise SystemExit("No se encontró pg_dump en el contenedor.") from None
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"pg_dump falló con código {error.returncode}.") from None


if __name__ == "__main__":
    main()
