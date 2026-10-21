def check_input(genomes_tsv_path) {
    def input = new File(genomes_tsv_path.toString())
    if (!input.isFile() || !input.canRead()) {
        throw new IllegalArgumentException("Cannot read genome TSV: ${input}")
    }
    def expectedColumns = ['genome', 'species', 'representative', 'genome_is_representative', 'fasta_path']
    def speciesMap = [:].withDefault { [genomes: [], representatives: [], declared: []] }
    def genomeSet = new HashSet()
    input.withReader { reader ->
        def header = reader.readLine()
        if (header == null || header.split('\t', -1).toList() != expectedColumns) {
            throw new IllegalArgumentException("Expected TSV headers: ${expectedColumns.join(', ')}")
        }
        reader.eachLine { line ->
            def fields = line.split('\t', -1)
            if (fields.size() != 5 || fields.any { !it || it != it.trim() }) {
                throw new IllegalArgumentException("Expected five nonempty fields without surrounding whitespace: ${line}")
            }
            def (genome, species, representative, isRepresentative, fasta) = fields
            [genome, species, representative].each { id ->
                if (!(id ==~ /[A-Za-z0-9][A-Za-z0-9_.-]*/)) {
                    throw new IllegalArgumentException("Unsafe genome/species identifier: ${id}")
                }
            }
            if (!(isRepresentative in ['0', '1'])) {
                throw new IllegalArgumentException("genome_is_representative must be 0 or 1: ${genome}")
            }
            if (!genomeSet.add(genome)) {
                throw new IllegalArgumentException("Duplicate genome ID: ${genome}")
            }
            // Relative paths retain the original contract: relative to the launch directory.
            def fastaPath = new File(fasta)
            if (!fastaPath.isFile() || !fastaPath.canRead() || fastaPath.length() == 0) {
                throw new IllegalArgumentException("Missing, unreadable or empty FASTA for ${genome}: ${fasta}")
            }
            // Existing external-tool command lines require paths without shell metacharacters.
            if (!(fastaPath.absolutePath ==~ /[A-Za-z0-9_\/.+-]+/)) {
                throw new IllegalArgumentException("FASTA path contains unsupported characters: ${fasta}")
            }
            speciesMap[species].genomes << genome
            speciesMap[species].declared << representative
            if (isRepresentative == '1') speciesMap[species].representatives << genome
        }
    }
    if (genomeSet.isEmpty()) {
        throw new IllegalArgumentException('Genome TSV contains no genomes.')
    }
    speciesMap.each { species, group ->
        if (group.representatives.size() != 1) {
            throw new IllegalArgumentException("Species ${species} must have exactly one representative; found ${group.representatives.size()}.")
        }
        def representative = group.representatives[0]
        if (group.declared.any { it != representative }) {
            throw new IllegalArgumentException("Species ${species}: representative must be ${representative} on every row.")
        }
    }
}
