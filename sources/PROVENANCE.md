# Benchmark provenance and interpretation

The instructor archive contains the 32 original STTRPSD instances published by
Juan G. Villegas and colleagues. These are benchmark data, not generated
classroom substitutes. The original text files are preserved under
`instructor/raw/`; their canonical JSON conversions are under
`instructor/instances/`. A selection for classroom use is supplied separately.

## Primary references

Juan G. Villegas, Christian Prins, Caroline Prodhon, Andrés L. Medaglia and
Nubia Velasco. **GRASP/VND and multi-start evolutionary local search for the
single truck and trailer routing problem with satellite depots.**
*Engineering Applications of Artificial Intelligence* 23(5), 780–794, 2010.
<https://doi.org/10.1016/j.engappai.2010.01.013>.

- Problem entry: <https://vrp-rep.org/variants/item/sttrpsd.html>.
- Dataset entry: <https://vrp-rep.org/datasets/item/villegas-et-al-2010.html>;
  VRP-REP identifier **2022-0001**, contributed by Juan G. Villegas, 32 instances.
- Author download page: <https://juangvillegas.com/download/>.
- Author-linked original archive:
  <https://www.dropbox.com/s/l0184eci283519t/STTRPSD.zip?dl=1>.
- Retrieved on **9 November 2026**. Archive SHA-256:
  `4c00eccaea86095dd00b07135fbf460d1784d3f997e295b22c2c74d90748272a`.

The author archive's README is retained verbatim in `benchmark_README.txt`.
Per-file hashes appear in `instructor/raw/manifest.json` and in the canonical
instances' metadata. Keep this attribution and the source README with any
selected benchmark files. The archive contains no separate explicit licence;
this package does not assign a new licence to the benchmark data.

## Exact source format

The first row gives the number of customers `n` and the number of depots
**including the main depot**, `p + 1`. The second row gives truck capacity and
trailer capacity. The next `p + 1` rows give depot coordinates `x y`, main depot
first. The final `n` rows give customer coordinates and demand `x y demand`.
Fields are separated by whitespace, with no explicit node identifiers.

The converter numbers the main depot `0`, satellites `1` through `p`, and
customers `p + 1` through `p + n`. The source filename convention is
`STTRP-n-p-Q-x.dat`, where `Q` is truck capacity divided by 1000 and `x` is `c`
for clustered or `rd` for randomly distributed locations. The source README
specifies **unrounded Euclidean distance**. No TSPLIB integer rounding is used.

The source instances use customer counts 25, 50, 100 and 200, satellite counts
5, 10 and 20, and truck capacities 1000 and 2000. Every supplied instance
satisfies individual demand at most the truck capacity and total demand at
most the sum of truck and trailer capacities. These checks concern input
feasibility; a solver must additionally respect truck capacity on every trip.

## Caveats for constructing teaching and evaluation sets

Although the paper describes a 100 by 100 generation region, some actual
clustered instance coordinates exceed 100. The converter preserves those
values and does not impose a coordinate box.

The two truck-capacity variants of each instance have identical depot and
customer geometry and identical demands. Across the 32 files there are 16
distinct complete geometry-and-demand layouts. In addition, for each customer
count, the `rd` instances with different numbers of satellites share the same
customer coordinates and demands. There are therefore only 12 distinct
customer-coordinate-and-demand layouts. These observations were checked
directly against the downloaded original data.

A file-disjoint split can still share a customer layout. Preserve such family
groupings when a stronger distinction between development and evaluation is
desired, and record the resulting distribution of sizes and geometry types.
All original benchmark instances are public: withholding the evaluation
selection does not make their coordinates secret or establish that the
instances were never seen during development.

## Prepared course selection

The supplied public set contains ten original instances. The instructor's
evaluation set contains ten other original instances, with no customer layout
appearing in both sets. Both selections have the same separate marginal
counts: 3 instances with 25 customers, 3 with 50, 2 with 100 and 2 with 200;
5 clustered and 5 random; 5 with truck capacity 1000 and 5 with capacity 2000;
and 3 with 5 satellites, 5 with 10 and 2 with 20.

These are marginal balances, not joint balances. In particular, matching
customer count jointly with `c`/`rd` is incompatible with withholding the
single random customer layout available at each size. The selection keeps
the family distinction and matches the four marginals above. Other feature
combinations can differ between the two sets. The instructor manifest
records the choices and their hashes. The public manifest lists public
instances only.
