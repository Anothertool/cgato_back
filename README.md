# CGato Backend

Backend Django con PostgreSQL y Django REST Framework.

## Ejecución local

## Descargar la base de producción

Después de desplegar estos cambios, abre el shell del servicio `cgato_back`
en el entorno `production` de Railway y ejecuta:

```sh
cd /app
python -m commons.export_database
```

El comando imprime la ruta del volcado en `/tmp`. Desde una carpeta local fuera
del repositorio, descárgalo con `scp`. Sustituye `ID_INSTANCIA` por el **Service
Instance ID** de `cgato_back` y usa la ruta que imprimió Python. Necesitas una
clave SSH registrada en Railway (`railway ssh keys add`).

```sh
scp ID_INSTANCIA@ssh.railway.com:/tmp/cgato-EJEMPLO.dump .
```

Si prefieres generarlo y descargarlo en una sola operación desde Bash local,
usa SSH sin terminal para conservar el formato binario:

```sh
ssh -T ID_INSTANCIA@ssh.railway.com 'cd /app && python -m commons.export_database --stdout' > cgato-produccion.dump.partial && mv cgato-produccion.dump.partial cgato-produccion.dump
```

El volcado contiene datos de producción. Si lo generaste en `/tmp`, bórralo
del contenedor después de verificar la descarga.

Para restaurarlo, usa PostgreSQL 18 y sus herramientas de cliente. Apunta a
una base local vacía y sustituye el nombre de archivo por el de tu volcado:

```sh
createdb --host=localhost --username=cgato cgato_copia
pg_restore --host=localhost --username=cgato --dbname=cgato_copia --single-transaction --no-owner --no-privileges cgato-produccion.dump
```
