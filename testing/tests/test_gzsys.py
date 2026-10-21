"""Bounded regressions; run with python3 -m unittest discover -s testing/tests -v.

Nextflow tests use NXF_OFFLINE=true and an isolated temporary launch directory.
No biological tools, downloads or real scheduler jobs are used.
"""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import contextlib
import io
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('check_gzsys', ROOT / 'bin/check_gzsys.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class PreflightTests(unittest.TestCase):
    def test_rejects_nonshared_paths(self):
        errors = preflight.check({'gzsys_root': '/tmp/midas'})
        self.assertTrue(any('gzsys_root' in error for error in errors))

    def test_missing_databases_fail_before_submission(self):
        params = {name: '/share/midas-test/missing' for name in (
            'gzsys_root', 'db_output_dir', 'eggnog_db_dir', 'genomad_db_dir',
            'resfinder_db_dir', 'genomes_tsv_path')}
        with patch.object(preflight.shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(1, 0, 200 * 1024**3)):
            with contextlib.redirect_stdout(io.StringIO()):
                errors = preflight.check(params)
        self.assertTrue(any('database component' in error for error in errors))

    def test_large_concurrency_rejected_for_initial_acceptance(self):
        params = {name: '/share/midas-test/missing' for name in (
            'gzsys_root', 'db_output_dir', 'eggnog_db_dir', 'genomad_db_dir',
            'resfinder_db_dir', 'genomes_tsv_path')}
        params.update(download_databases=True, gzsys_queue_size=12)
        with patch.object(preflight.shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(1, 0, 200 * 1024**3)):
            with contextlib.redirect_stdout(io.StringIO()):
                errors = preflight.check(params)
        self.assertTrue(any('gzsys_queue_size' in error for error in errors))


class PrebuildTests(unittest.TestCase):
    def test_shared_environment_config_without_installing_packages(self):
        with tempfile.TemporaryDirectory(prefix='midas-conda-test-') as directory:
            root = Path(directory)
            fakebin = root / 'bin'
            fakebin.mkdir()
            conda = fakebin / 'conda'
            conda.write_text('#!/bin/bash\nwhile [[ $# -gt 0 ]]; do\nif [[ "$1" == --prefix ]]; then mkdir -p "$2/conda-meta"; touch "$2/conda-meta/history"; exit 0; fi\nshift\ndone\nexit 1\n')
            conda.chmod(0o755)
            config = root / 'shared.config'
            original = (ROOT / 'conf/conda_envs.config').read_bytes()
            env = dict(os.environ, PATH=str(fakebin) + os.pathsep + os.environ['PATH'])
            result = subprocess.run(['bash', str(ROOT / 'bin/prebuild_conda_envs.sh'),
                                     '--env-dir', str(root / 'envs'), '--config-out', str(config)],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((ROOT / 'conf/conda_envs.config').read_bytes(), original)
            self.assertIn("withName: 'ClusterCentroidsLowerThresholds'", config.read_text())
            self.assertIn(str(root / 'envs/prokka'), config.read_text())


class PipelineFailureTests(unittest.TestCase):
    def test_cdhit_failure_stops_before_success_marker(self):
        with tempfile.TemporaryDirectory(prefix='midas-pipeline-test-') as directory:
            root = Path(directory)
            fakebin = root / 'bin'
            fakebin.mkdir()
            grep = fakebin / 'grep'
            grep.write_text('#!/bin/bash\nif [[ "$1" == -oP ]]; then echo 99; else exec /usr/bin/grep "$@"; fi\n')
            grep.chmod(0o755)
            cdhit = fakebin / 'cd-hit-est'
            cdhit.write_text('#!/bin/bash\nexit 42\n')
            cdhit.chmod(0o755)
            for name, text in {
                'centroids.99.clean.ffn': '>g1\nATGC\n',
                'centroids.99.ambiguous.ffn': '',
                'genes.ffn': '>g1\nATGC\n',
                'genes.len': 'g1\tg\t4\n',
                'gene_info.txt': 'gene_id\tcentroid_99\ng1\tg1\n',
            }.items():
                (root / name).write_text(text)
            result = subprocess.run(['bash', str(ROOT / 'bin/pipeline.sh'), 's1',
                                     'gene_info.txt', 'centroids.99.clean.ffn',
                                     'centroids.99.ambiguous.ffn', 'genes.ffn', 'genes.len', '1', '1024'],
                                    cwd=root, env=dict(os.environ, PATH=str(fakebin) + os.pathsep + os.environ['PATH']),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
            self.assertFalse((root / 'temp/cdhit/PIPELINE_SUCCESS').exists())


@unittest.skipUnless(shutil.which('nextflow'), 'Nextflow not on PATH')
class NextflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='midas-tests-')
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.env = dict(os.environ, NXF_OFFLINE='true', NXF_ANSI_LOG='false', NXF_SYNTAX_PARSER='v1')
        self.fasta = self.path / 'g.fa'
        self.fasta.write_text('>contig\nATGC\n')

    def nf(self, *args):
        return subprocess.run(['nextflow', *map(str, args)], cwd=self.path,
                              env=self.env, capture_output=True, text=True, timeout=90)

    def preview(self, rows):
        tsv = self.path / 'genomes.tsv'
        tsv.write_text('genome\tspecies\trepresentative\tgenome_is_representative\tfasta_path\n' + '\n'.join(
            '\t'.join([*r, str(self.fasta)]) for r in rows) + '\n')
        return self.nf('run', ROOT / 'main.nf', '--genomes_tsv_path', tsv,
                       '--db_output_dir', self.path / 'out', '-preview')

    def test_two_species_compile_without_creating_db_output(self):
        result = self.preview([['g1', 's1', 'g1', '1'], ['g2', 's2', 'g2', '1']])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.path / 'out').exists())

    def test_prepared_database_mode_compiles_on_cluster_profile(self):
        for directory in ('eggnog/data', 'genomad/genomad_db', 'resfinder/resfinder_db', 'resfinder/disinfinder_db'):
            (self.path / directory).mkdir(parents=True)
        # Bundled TSV paths are launch-relative, so use a temporary TSV with absolute FASTAs.
        tsv = self.path / 'absolute.tsv'
        tsv.write_text((ROOT / 'testing/inputs/genomes.tsv').read_text().replace('./testing/', str(ROOT / 'testing') + '/'))
        result = self.nf('run', ROOT / 'main.nf', '-profile', 'gzsys',
                         '--genomes_tsv_path', tsv, '--gzsys_root', self.path,
                         '--eggnog_db_dir', self.path / 'eggnog',
                         '--genomad_db_dir', self.path / 'genomad',
                         '--resfinder_db_dir', self.path / 'resfinder', '-preview')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('WARN:', result.stdout + result.stderr)

    def test_missing_representative_fails(self):
        result = self.preview([['g1', 's1', 'g1', '0']])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('exactly one representative', result.stdout + result.stderr)

    def test_inconsistent_representative_fails(self):
        result = self.preview([['g1', 's1', 'g1', '1'], ['g2', 's1', 'g2', '0']])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('representative must be g1', result.stdout + result.stderr)

    def test_duplicate_genome_fails(self):
        result = self.preview([['g1', 's1', 'g1', '1'], ['g1', 's1', 'g1', '0']])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Duplicate genome ID', result.stdout + result.stderr)

    def test_cluster_profile_uses_native_sge_memory(self):
        result = self.nf('config', ROOT, '-profile', 'gzsys', '-flat')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("process.executor = 'sge'", result.stdout)
        self.assertIn("process.penv = 'smp'", result.stdout)
        self.assertIn('executor.queueSize = 3', result.stdout)
        self.assertNotIn('h_vmem', result.stdout)
        self.assertNotIn('h_rss=', result.stdout)  # emitted by SgeExecutor, not clusterOptions
        self.assertNotIn('WARN:', result.stdout + result.stderr)

    def test_sge_script_with_fake_scheduler(self):
        # Exercise Nextflow's actual SgeExecutor, capturing generated submission headers.
        fakebin = self.path / 'fakebin'
        fakebin.mkdir()
        qsub = fakebin / 'qsub'
        qsub.write_text('#!/bin/bash\nset -e\nscript="${@: -1}"\ncp "$script" "$MIDAS_CAPTURE"\nbash "$script" > /dev/null 2>&1\necho 12345\n')
        qsub.chmod(0o755)
        qstat = fakebin / 'qstat'
        qstat.write_text('#!/bin/bash\nexit 0\n')
        qstat.chmod(0o755)
        self.env['PATH'] = str(fakebin) + os.pathsep + self.env['PATH']
        self.env['MIDAS_CAPTURE'] = str(self.path / 'submitted.sh')
        workflow = self.path / 'probe.nf'
        workflow.write_text('''process Probe {
    label 'mem_high'
    conda false
    output:
    path 'ok.txt'
    script:
    "echo ok > ok.txt"
}
workflow { Probe() }
''')
        config = self.path / 'probe.config'
        config.write_text(f"includeConfig '{ROOT}/conf/gzsys.config'\nworkDir = '{self.path}/work'\nconda.enabled = false\nexecutor.pollInterval = '1 sec'\n")
        result = self.nf('-C', config, 'run', workflow)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        script = (self.path / 'submitted.sh').read_text()
        self.assertIn('#$ -q all.q', script)
        self.assertIn('#$ -pe smp 8', script)
        self.assertIn('h_rss=16384M,mem_free=16384M', script)
        self.assertNotIn('h_vmem', script)
        self.assertEqual(script.count('h_rss='), 1)


if __name__ == '__main__':
    unittest.main()
