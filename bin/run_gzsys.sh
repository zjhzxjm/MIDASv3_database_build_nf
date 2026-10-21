#!/usr/bin/env bash
# Explicit run modes: --check is read-only; --preview writes local Nextflow metadata;
# --run submits SGE jobs and may prepare databases if enabled in the JSON.
set -euo pipefail
# The upstream workflow uses Groovy DSL2 syntax supported by the v1 parser.
export NXF_SYNTAX_PARSER=v1
if [[ $# -lt 2 || ! "$1" =~ ^--(check|preview|run)$ ]]; then
    echo "Usage: $0 --check|--preview|--run PARAMS.json [-resume [SESSION]]" >&2
    exit 2
fi
mode="$1"
params_file="$2"
shift 2
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$project_dir/bin/check_gzsys.py" "$params_file"
nextflow config "$project_dir" -profile gzsys -flat >/dev/null
if [[ "$mode" == --check ]]; then
    exit 0
fi
if [[ "$mode" == --preview ]]; then
    exec nextflow run "$project_dir/main.nf" -profile gzsys -params-file "$params_file" -preview "$@"
fi
exec nextflow run "$project_dir/main.nf" -profile gzsys -params-file "$params_file" "$@"
