#!/usr/bin/env python3
"""Read-only deployment preflight. No downloads, environment creation or job submission."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


def check(params, effective):
    errors = []
    legacy = {'gzsys_root', 'gzsys_queue', 'gzsys_penv', 'gzsys_queue_size', 'conda_envs_config'}
    if legacy.intersection(params):
        errors.append('Move execution settings from JSON to DEPLOY.config: ' + ', '.join(sorted(legacy.intersection(params))))
    execution_paths = {
        'workDir': effective.get('workDir'),
        'conda.cacheDir': effective.get('conda', {}).get('cacheDir'),
    }
    for name, value in execution_paths.items():
        if not isinstance(value, str) or not value.startswith('/share/') or not re.fullmatch(r'[A-Za-z0-9_/.+-]+', value):
            errors.append(f'Effective {name} must be an absolute /share/ path without shell metacharacters')
    process = effective.get('process', {})
    executor = effective.get('executor', {})
    queue_size = executor.get('queueSize')
    sge_queue_size = executor.get('$sge', {}).get('queueSize', queue_size)
    for name, value in (('executor.queueSize', queue_size),
                        ('executor.$sge.queueSize', sge_queue_size)):
        if type(value) is not int or not 1 <= value <= 24:
            errors.append(f'Effective {name} must be between 1 and 24')
    if process.get('executor') != 'sge' or not process.get('queue') or not process.get('penv'):
        errors.append('Effective executor/queue/penv must select an SGE queue and parallel environment')
    if effective.get('conda', {}).get('enabled') is not True:
        errors.append('Effective conda.enabled must be true')
    print('Effective execution:', json.dumps({**execution_paths, 'queueSize': sge_queue_size,
          'queue': process.get('queue'), 'penv': process.get('penv')}, sort_keys=True))
    conda_selections = {name: value.get('conda') for name, value in process.items()
                        if isinstance(value, dict) and value.get('conda') is not None}
    if process.get('conda') is not None:
        conda_selections['default'] = process['conda']
    for selector, value in sorted(conda_selections.items()):
        print(f'Effective Conda {selector}: {value}')
        if isinstance(value, str) and value.startswith('/'):
            path = Path(value)
            if path.suffix in ('.yml', '.yaml'):
                if not path.is_file():
                    errors.append(f'Missing Conda YAML for {selector}: {path}')
            elif not (path / 'conda-meta/history').is_file():
                errors.append(f'Incomplete Conda environment for {selector}: {path}')
    if not conda_selections:
        print('Effective Conda: process-local YAML definitions (no deployment overrides)')
    for name in ('db_output_dir', 'eggnog_db_dir', 'genomad_db_dir',
                 'resfinder_db_dir', 'genomes_tsv_path'):
        value = params.get(name)
        if not isinstance(value, str) or not value.startswith('/share/'):
            errors.append(f'{name} must be an absolute /share/ path in the parameters JSON')
        elif not re.fullmatch(r'[A-Za-z0-9_/.+-]+', value):
            errors.append(f'{name} contains unsupported path characters')
    if errors:
        return errors

    for name in ('db_output_dir', 'eggnog_db_dir', 'genomad_db_dir', 'resfinder_db_dir'):
        ancestor = Path(params[name])
        while not ancestor.exists():
            ancestor = ancestor.parent
        minimum = float(params.get('gzsys_min_free_gb', 100))
        free_gb = shutil.disk_usage(ancestor).free / 1024**3
        print(f'{name}: {params[name]} (free {free_gb:.1f} GiB)')
        if free_gb < minimum:
            errors.append(f'{name}: less than required {minimum:g} GiB free')

    genomes = Path(params['genomes_tsv_path'])
    if not genomes.is_file():
        errors.append(f'Genome TSV does not exist: {genomes}')
    required = {
        'eggnog_db_dir': ['data/eggnog.db', 'data/eggnog_proteins.dmnd', 'data/eggnog.taxa.db', 'data/pfam'],
        'genomad_db_dir': ['genomad_db'],
        'resfinder_db_dir': ['resfinder_db', 'disinfinder_db'],
    }
    required['eggnog_db_dir'][1] = 'data/' + params.get('eggnog_dmnd_db_name', 'eggnog_proteins.dmnd')
    if params.get('download_databases', False):
        print('Database preparation enabled: a subsequent run may download large databases on the login node.')
    else:
        for name, entries in required.items():
            for entry in entries:
                path = Path(params[name]) / entry
                if not path.exists() or (path.is_file() and path.stat().st_size == 0):
                    errors.append(f'Missing or empty database component: {path}')
    if not isinstance(params.get('download_databases', False), bool):
        errors.append('download_databases must be a JSON boolean')
    print('Check the same code, input, database, work and Conda paths on every selected execution node before submission.')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('params_json', type=Path)
    parser.add_argument('--effective-config', type=Path, required=True)
    args = parser.parse_args()
    try:
        params = json.loads(args.params_json.read_text())
        if not isinstance(params, dict):
            raise ValueError('Parameters JSON must be an object')
        effective = json.loads(args.effective_config.read_text())
        if not isinstance(effective, dict):
            raise ValueError('Effective configuration must be an object')
        errors = check(params, effective)
    except (OSError, ValueError, TypeError) as exc:
        errors = [str(exc)]
    for executable in ('nextflow', 'java', 'conda', 'qsub', 'qstat'):
        if not shutil.which(executable):
            errors.append(f'{executable} is not available on PATH')
    if shutil.which('java'):
        result = subprocess.run(['java', '-version'], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True)
        version = re.search(r'version "(\d+)', result.stderr + result.stdout)
        if result.returncode or not version or int(version[1]) < 17:
            errors.append('Java 17 or later is required; use the shared Nextflow runtime.')
    for error in errors:
        print(f'ERROR: {error}', file=sys.stderr)
    if errors:
        return 1
    print('Login-node preflight passed. Compute-node visibility and scientific results require separate verification.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
