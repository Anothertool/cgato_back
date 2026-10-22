from zipfile import BadZipFile

from django.core.management.base import BaseCommand, CommandError
from openpyxl.utils.exceptions import InvalidFileException

from cash.utils import import_cash


"""
python manage.py import_cash cash/CGato_cobros_2025_2026.xlsx --dry-run
python manage.py import_cash cash/CGato_cobros_2025_2026.xlsx
"""


class Command(BaseCommand):
    help = 'Importa movimientos históricos de Caja desde un Excel con external_id.'

    def add_arguments(self, parser):
        parser.add_argument('path', help='Ruta del archivo .xlsx.')
        parser.add_argument('--dry-run', action='store_true', help='Valida y revierte todos los cambios.')

    def handle(self, *args, **options):
        try:
            summary = import_cash(
                options['path'], dry_run=options['dry_run'],
                report=self.stderr.write,
            )
        except (OSError, ValueError, BadZipFile, InvalidFileException) as exc:
            raise CommandError(str(exc)) from exc

        if options['dry_run']:
            self.stdout.write('DRY RUN: simulación; todos los cambios se han revertido.')
        for key, label in (
            ('cash_created', 'Cobros creados'),
            ('patients_created', 'Pacientes creados'),
            ('with_surgery', 'Cobros asociados a cirugías'),
            ('without_surgery', 'Cobros sin cirugía'),
            ('duplicates', 'Registros duplicados omitidos'),
            ('errors', 'Filas con errores'),
        ):
            self.stdout.write(f'{label}: {summary[key]}')
