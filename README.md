# MIDAS3 Database Build Pipeline

## Overview

This Nextflow pipeline is designed to create a custom database from a set of prokaryote genome assemblies for use with MIDAS (version 3). 

---

## Installation

### 1. Requirements

- **Nextflow:** Install [Nextflow](https://www.nextflow.io/). This pipeline has been tested on versions 23.10.0 and 24.10.5.
- **Conda:** Install [Conda](https://docs.conda.io/en/latest/miniconda.html) (Miniconda or Anaconda) for environment management.

### 2. Prebuild Conda Environments

To save time during execution and ensure stability on HPC clusters, run the prebuild script. This creates all necessary environments in a `.conda_envs/` directory and generates a configuration file so Nextflow knows where to find them.
```bash
bash bin/prebuild_conda_envs.sh
```

> **Note:** The default command modifies `conf/conda_envs.config`. To preserve the checkout, pass `--config-out /absolute/path/conda.config` and include the generated file from your explicit deployment config.

### 3. HPC Configuration

The included `nextflow.config` is pre-configured for SGE on UCSF's Wynton cluster. Update the `process` and `executor` settings in `nextflow.config` to match your specific system or HPC (e.g., Slurm, LSF).

---

## Database Setup

This pipeline handles the installation of the EggNOG, geNomad, and ResFinder databases automatically.

- Specify the desired installation paths for these databases in your `params.json`.
- If the specified directories do not exist, the pipeline will automatically trigger download processes (run locally).
  
---

## Inputs

Genome assemblies must already be clustered into species or species-level genome bins. Provide a TSV file with the following five columns:

| Column | Description |
|--------|-------------|
| `genome` | The name of the genome. |
| `species` | A unique identifier for the species cluster (e.g., a 6-digit ID). |
| `representative` | The name of the representative genome for that cluster. |
| `genome_is_representative` | `1` if the genome is the representative, `0` otherwise. |
| `fasta_path` | The full path to the genome assembly file. |

**Example `genomes.tsv`:**

| genome | species | representative | genome_is_representative | fasta_path |
|--------|---------|----------------|--------------------------|------------|
| GCA_900552055.1 | 117086 | GCA_900552055.1 | 1 | /path/to/genomes/GCA_900552055.1.fasta |
| GCF_900752885.1 | 117086 | GCA_900552055.1 | 0 | /path/to/genomes/GCF_900752885.1.fasta |

---

## Parameters

### Required Parameters (`params.json`)

| Parameter | Description |
|-----------|-------------|
| `eggnog_db_dir` | Directory where EggNOG data is stored/downloaded. |
| `genomad_db_dir` | Directory where geNomad data is stored/downloaded. |
| `resfinder_db_dir` | Directory where ResFinder/PointFinder data is stored/downloaded. |
| `eggnog_dmnd_db_name` | Name of the EggNOG Diamond database (usually `eggnog_proteins.dmnd`). |
| `marker_set` | Marker set for HMM models (default: `phyeco`). |

### Optional Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--db_name` | Name of the output database. | `nextflow_db` |
| `--db_output_dir` | Parent directory for the database output. | `.` |
| `--centroid_cluster_percents` | Identity thresholds for clustering. MIDAS expects databases to have the default thresholds. | `[99, 95, 90, 85, 80, 75]` |

---

## Usage

To run the pipeline with a parameters file:
```bash
nextflow run main.nf -c nextflow.config -params-file params.json --genomes_tsv_path genomes.tsv
```

### Resume Execution

If a run fails or is interrupted, use the `-resume` flag to pick up where it left off:
```bash
nextflow run main.nf -c nextflow.config -params-file params.json -resume
```

### Example Test Run
```bash

bash bin/prebuild_conda_envs.sh

nextflow run main.nf \
  -c nextflow.config \
  -params-file params.json \
  --genomes_tsv_path testing/inputs/genomes.tsv \
  --db_output_dir testing \
  -w testing/work
```

---

## Prome branch: gzsys-xujm

Use `-profile gzsys` for this cluster. The profile selects SGE `all.q` with the
`smp` parallel environment and uses Nextflow's native `h_rss` / `mem_free` memory
requests. Do not combine it with the upstream `standard` profile, which contains
Wynton-specific resource settings. The upstream Groovy DSL2 code requires
`NXF_SYNTAX_PARSER=v1` on newer Nextflow releases; the launcher sets this explicitly.

The initial limit is three concurrent jobs, with each task capped at 32 GiB,
including retries. `RunGeNomad` requests 32 GiB from its first attempt; the
four-genome SGE sample reported approximately 18.5 GB peak RSS per geNomad task.
This is intentionally conservative because this cluster's
`mem_free` does not reserve aggregate memory. Measure real workloads and node
headroom before increasing concurrency or memory. A terminated task fails the
workflow after the bounded retries; the profile does not ignore failed builds.

`params.gzsys.json` contains pipeline inputs, outputs and database paths.
`gzsys.config` is the explicit deployment template for `workDir`, `conda.cacheDir`,
`executor.queueSize`, queue, parallel environment and optional prebuilt Conda
selectors. Copy and edit both files for the run. The templates use
`/share/data7/Project/xujm/MIDASv3`; their presence does not prove that these
directories or databases exist. Use absolute shared paths for the checkout,
inputs, work, results, databases and environments. These paths must be visible
under the same names on every selected compute node. Preserve the launch
directory's `.nextflow` cache and shared `work` directory to resume a run.

On the login node, initialize the existing runtime (verified on 2026-10-21 as
Nextflow 26.04.0 with Java 21; package availability is still to be validated):

```bash
source /share/data7/apps/miniconda3/etc/profile.d/conda.sh
conda activate /share/data7/apps/miniconda3/envs/nextflow
export NXF_SYNTAX_PARSER=v1
```

Prepare a dedicated shared set of environments. This command installs packages;
it is a deployment step and can take substantial time and disk space. Use Bash 4
or later on Linux. Existing analysis-tool version constraints are retained.
The EggNOG and geNomad environments pin `c-ares` to `1.34.6=hb03c661_0`. Their full
environments were separately solved, installed, and checked on gzsys glibc 2.17,
retaining EggNOG 2.1.12, DIAMOND 2.1.9, geNomad 1.7.0, and all other dependency
constraints. These environment checks do not establish reference-database annotation
or full SGE pipeline acceptance. The package download cache below is separate
from the environment prefixes; use a user-writable cache to avoid permission
errors on partial downloads in the shared Miniconda installation.

The ResFinder pip stack pins ResFinder 4.6.0, MobileElementFinder 1.1.2,
cgecore 1.5.6, Biopython 1.80, pandas 2.2.3 and NumPy 1.26.4. This avoids the
incompatible Biopython requirements of ResFinder 4.7.2/cgecore 2.0.1 and
MobileElementFinder 1.1.2, and uses a pandas wheel compatible with glibc 2.17.

```bash
CONDA_PKGS_DIRS=/share/data7/Project/xujm/MIDASv3/conda-pkgs \
bash bin/prebuild_conda_envs.sh \
  --env-dir /share/data7/Project/xujm/MIDASv3/conda-prebuilt \
  --config-out /share/data7/Project/xujm/MIDASv3/conda.config
```

Uncomment `includeConfig '/share/data7/Project/xujm/MIDASv3/conda.config'` in the
run's deployment config to select those environments. Without that include,
Nextflow creates environments on demand in the shared Conda cache. Existing
prefixes must contain `conda-meta/history`. For YAMLs with pip dependencies, the
prebuild script also checks that every declared pip package is installed at an
allowed version and that `pip check` succeeds, both before reuse and after creation.
A failed pip install can leave Conda history behind; that prefix is rejected and
the existing deployment config is preserved. Repair the named prefix, or move it
to a backup path before rerunning. Rebuilding in place requires an explicit
`--force`. The prebuild script checks out no code and submits no scheduler jobs. `--force` removes and rebuilds
only its named environment prefixes; avoid it for environments used by live jobs.

Database roots follow the existing download layout:

| JSON parameter | Required content below that directory |
|---|---|
| `eggnog_db_dir` | `data/eggnog.db`, `data/eggnog_proteins.dmnd`, `data/eggnog.taxa.db`, `data/pfam/` |
| `genomad_db_dir` | The extracted `genomad_db/` directory |
| `resfinder_db_dir` | Installed `resfinder_db/` and `disinfinder_db/` directories |

Reuse databases only when their tool/version compatibility and installation are
confirmed. The preflight checks expected paths, not index integrity or scientific
compatibility. `download_databases` defaults to `false` in this profile; a missing
database causes a failure rather than an automatic download. Explicitly setting
it to `true` enables the upstream database download/install processes on the
login node. Downloading databases is separate from environment preparation.

After copying the checkout and preparing the inputs and databases, run from a
dedicated launch directory on shared storage:

```bash
# Read-only login-node checks, including the final effective execution configuration.
bash /path/to/checkout/bin/run_gzsys.sh --check /path/to/run-params.json /path/to/deploy.config

# Validate the input TSV and compile the complete workflow; submit no jobs.
# Nextflow writes its log/cache metadata in the launch directory.
bash /path/to/checkout/bin/run_gzsys.sh --preview /path/to/run-params.json /path/to/deploy.config

# Submit the real workflow only after checking all compute-node paths.
bash /path/to/checkout/bin/run_gzsys.sh --run /path/to/run-params.json /path/to/deploy.config

# Resume from the same launch directory with the same retained work/cache.
bash /path/to/checkout/bin/run_gzsys.sh --run /path/to/run-params.json /path/to/deploy.config -resume
```

Inspection and execution use the identical explicit configuration set:
`-C /path/to/checkout/nextflow.config,/path/to/deploy.config -profile gzsys`.
Home and launch-directory configs are excluded. The check inspects Nextflow's
JSON configuration output, prints the effective work/cache directories, queue,
parallel environment, concurrency and Conda overrides, and validates referenced
prefix markers. Extra execution overrides are rejected by the launcher; only
`-resume [SESSION]` is accepted for a run. Move the old JSON keys `gzsys_root`,
`gzsys_queue`, `gzsys_penv`, `gzsys_queue_size` and `conda_envs_config` into native
execution settings in the deployment config; the preflight rejects those old
keys so it cannot validate one set of settings and run another.

The genome TSV requires one representative per species, consistent
`representative` values and unique genome IDs. IDs accept letters, numbers, dots,
underscores and hyphens, starting with a letter or number. FASTA paths cannot
contain whitespace or shell metacharacters. Relative FASTA paths are resolved
against the launch directory; use absolute paths on the cluster. This build uses
the MIDAS thresholds `[99, 95, 90, 85, 80, 75]` because downstream code assumes the
99% primary clustering level.

A successful preview or accepted SGE job is not acceptance of a database build.
First run the bundled four-genome/two-species example using a separate output and
work directory. Verify every expected genome and species, marker indexes,
`genes_info.tsv`, `centroids.ffn`, cluster information/annotation tables and chunk
JSON files, and inspect the trace for failed or missing tasks before a larger
build. The profile writes timestamped trace, HTML report and timeline files in
the launch directory. The separate `modules/rarefaction.nf` workflow is outside
this cluster adaptation's acceptance scope.

Local regression checks (no downloads or real scheduler jobs):

```bash
NXF_OFFLINE=true python3 -m unittest discover -s testing/tests -v
```

These checks compile the workflow, exercise representative-input failures and
inspect a real Nextflow-generated SGE submission script through a fake scheduler.
They do not replace a Linux Conda environment build or a biological end-to-end run.

## Citation

If you use this tool, please cite:

- Dubin CA, Zhao C, Pollard KS, Oskotsky T, Golob JL, Sirota M. Expanding vaginal microbiome pangenomes via a custom MIDAS database reveals *Lactobacillus crispatus* accessory genes associated with cervical dysplasia. *bioRxiv*. 2025. doi:[10.1101/2025.09.11.675634](https://doi.org/10.1101/2025.09.11.675634)

- Smith BJ, Zhao C, Dubinkina V, Jin X, Zahavi L, Shoer S, Moltzau-Anderson J, Segal E, Pollard KS. Accurate estimation of intraspecific microbial gene content variation in metagenomic data with MIDAS v3 and StrainPGC. *Genome Res*. 2025. doi:[10.1101/gr.279543.124](https://doi.org/10.1101/gr.279543.124)
