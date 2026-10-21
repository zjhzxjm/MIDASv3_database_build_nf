#!/usr/bin/env bash
# --check submits no jobs; --preview writes Nextflow metadata; --run submits SGE jobs.
set -euo pipefail
export NXF_SYNTAX_PARSER=v1
if [[ $# -lt 3 || ! "$1" =~ ^--(check|preview|run)$ ]]; then
    echo "Usage: $0 --check|--preview|--run PARAMS.json DEPLOY.config [-resume [SESSION]]" >&2
    exit 2
fi
mode="$1"
params_file="$2"
deploy_config="$3"
shift 3
if [[ $# -gt 0 && ( "$mode" != --run || "$1" != -resume || $# -gt 2 ) ]]; then
    echo "Only -resume [SESSION] is supported; put execution settings in DEPLOY.config." >&2
    exit 2
fi
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Use exactly these config sources for both inspection and execution. Ignore implicit
# home/launch configs so an unchecked profile or selector cannot change the run.
config_sources="$project_dir/nextflow.config,$deploy_config"
effective_config="$(mktemp)"
trap 'rm -f "$effective_config"' EXIT
nextflow -C "$config_sources" config "$project_dir" -profile gzsys -o json > "$effective_config"
python3 "$project_dir/bin/check_gzsys.py" "$params_file" --effective-config "$effective_config"
rm -f "$effective_config"
if [[ "$mode" == --check ]]; then
    exit 0
fi
if [[ "$mode" == --preview ]]; then
    exec nextflow -C "$config_sources" run "$project_dir/main.nf" -profile gzsys -params-file "$params_file" -preview
fi
exec nextflow -C "$config_sources" run "$project_dir/main.nf" -profile gzsys -params-file "$params_file" "$@"
