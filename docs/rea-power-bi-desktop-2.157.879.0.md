# Power BI Desktop reverse engineering notes

## 2026-10-20 live-runtime access check

Power BI Desktop and the Windows 11 Parallels VM were still running. The VM
reported Parallels Guest Tools `outdated` at `27.0.2-58673`. REA process-capture
Evidence `ev_2f1314af7637fa74b2df9f1c16c1e08bb2792f8c2a6b98fd57662acd37e57f11`
attempted a read-only guest UIAutomation inventory through `prlctl exec`; the
guest returned `Unable to open new session in this virtual machine` (exit 255)
before the PowerShell script started. The capture recorded zero interaction
events and no filesystem observations. This is a Parallels access failure, not
evidence about Power BI behavior. No Guest Tools update, guest restart, or
Power BI action was performed. Live DAX-editor completion and a live Power
Query filter click therefore remain unverified in this pass.

## Target and evidence

The screenshots supplied on 2026-10-19 show Power BI Desktop at its start page
and an empty report canvas. The Windows Store package inventory in the running
Windows VM identifies `Microsoft.MicrosoftPowerBIDesktop` version `2.157.879.0`.
REA's managed artifact inspection identifies the staged `PBIDesktop.exe` as an
x64 PE/.NET assembly, SHA-256
`6c849963bf16ee42f31c0cb3fbf3761b4ae19016fe2af3cfb8bf5de249116405`.

The path supplied by the user,
`C:\Program Files\WindowsApps\Microsoft.MicrosoftPowerBIDesktop_2.157.879.0_x64__8wekyb3d8bbwe`,
is inside the Windows 11 Parallels guest. That installed package is also
mounted on macOS at
`/Volumes/[C] Windows 11.hidden/Program Files/WindowsApps/Microsoft.MicrosoftPowerBIDesktop_2.157.879.0_x64__8wekyb3d8bbwe`,
so both guest-side and direct mounted-file inspection are available. The
package inventory queried from the guest contains 7,263 files totaling
2,862,839,642 bytes. The largest file groups are 2,577 JavaScript files, 1,942
XML files, 1,805 DLLs, 240 PNGs, and 149 SVGs. The complete per-file manifest
is retained outside the repository at
`~/Library/Caches/codex-powerbi-rea/2.157.879.0/package-inventory.json`.

The embedded `bin/WebView2Resources/minerva` web application contains 3,047
files totaling 686,161,409 bytes. It includes report, model, data-exploration,
DAX-query, dialog-host, and TMDL HTML entrypoints, with corresponding large
JavaScript application and vendor bundles. REA copied this tree read-only to
`~/Library/Caches/codex-powerbi-rea/2.157.879.0/minerva` and analyzed the six
HTML entrypoints plus their twelve main/vendor JavaScript bundles as inert
text. The reanalysis retained the complete directory identity, but its semantic
graph is partial: three JavaScript files completed parsing and nine were
skipped after worker-heap or result-budget limits; 2,586 inventoried files
were outside the selected source set. It recorded 28,480 findings across
3,906 modules and visited 5,588,858 AST nodes. No bundled application code was
executed.

The current REA directory-analysis evidence is
`ev_29b47e01ab01a2ced53ec45c3363459b7ed2a2572342117ccbe19363c0359be3`; its
summary view is `ev_2299349184f085a7551851deebbde6562b205bb411febbe8b629fb1f69bc0f12`.
The Minerva directory digest is
`2495e1708e65c45172c319a2522e01c6bdc19802d6807d77c190fddef16de387`.

A focused REA analysis was also run against the installed package's mounted
`bin/WebView2Resources/minerva` directory, selecting only
`scripts/desktopDataExplore.MapVisuals.min.js` and
`sharedresources/Shapemaps/uk.countries.topo.json`. The JS and TopoJSON source
SHA-256 values match their REA-cache copies:
`afc452f03129c49958aa3e9bec67adab6f5d999de06165d286eeaafd3d1fdb95` and
`249d866e0a5024103358b958acab1d32944231bbbbcdba97ecf60d6d553a5b79`,
respectively. The focused parse recorded webpack chunk `MapVisuals` with three
bundled modules: `87599` (`Map`, `MapBehavior`), `80628` (opaque export `b`),
and `97386` (opaque export `X`). The TopoJSON is 11,623 bytes and has top-level
keys `arcs`, `objects`, `transform`, and `type`. This is static evidence about
the selected artifacts; no bundle code was executed and the analysis does not
reconstruct full map behavior.

The investigation used REA `rea-agents 6.7.0` and its managed static provider.
For complete instruction sequences beyond REA's CIL anchors, I also decoded
file-backed methods in the staged DLL with temporary `dnfile` 0.18.0 and
`dncil` 1.0.2 installs under `/tmp/pbi-rea-decoder`. Those packages are not
project dependencies, and the target assembly was not executed.
The retained evidence records are:

| Evidence ID | Artifact | Observation |
| --- | --- | --- |
| `ev_cb96192f121682ff7f44c3fc14c370dc08b0fd5c7a6df19a6a5ca5a5c25edd91` | `PBIDesktop.exe` | Managed PE identity and runtime metadata. |
| `ev_778d983469bbd44a163648b0be7ec6cecdd2153d526474cd496300c0055e1b08` | `Microsoft.PowerBI.Client.Windows.dll` | Selected `DataSourceHostService` members and static CIL anchors for data-view query construction, sorting, and filtering. |
| `ev_cece080def8c568eeb73eb456843ea0359ca7b2f1405196ff596ee5605af82dd` | `Microsoft.PowerBI.Client.Windows.dll` | Selected `ModelQueryInfo`, `ColumnSortInfo`, `ColumnFilterInfo`, and `JsonColumnSortFilterInfo` metadata. |
| `ev_010c75ceaa14337fbb55aaa324903bbe9f2d00ba33f7274766b3c6ec24b45334` | `Microsoft.PowerBI.Modeler.dll` | Model relationship subsystem members and metadata strings. |
| `ev_6f14f607a67a85bcc4e2ae4ada3f08ebc0a25b6b9b6061c4a94b5d102bfa68a2` | `Microsoft.PowerBI.Modeling.Engine.dll` | Relationship detection helper and fast detector members. |
| `ev_e32d8e815db901433ceec5b5e5c34463216f9aebdc7975169c3558f4f01d122f`, `ev_6e9056145578dfe1dd1864f6c0788f9fd22446ef557293e8463b2346b592172a` | `Microsoft.PowerBI.Modeling.Engine.dll` | Detector/helper CIL, including key-group limits, direct relationship mapping, scoped path-length filtering, connection checks, and async state machines; the analysis view confirms complete coverage of the six selected declaring types. |
| `ev_cc26e6d43df337ad16d1d3d901784527e351e52d6d0e7421c8a8cab649fcae64` | `Microsoft.PowerBI.Modeling.Engine.dll`, call-edge view | Resolves `FilterAndSortColumnPairs` calls to LINQ `Where`, `OrderBy`, and `Select`; the sort selector reads `ValueTuple.Item2`, and the final selector returns `Item1`. |
| `ev_4b7cf4765698367b157fdffbda63f5de84efcaa0403f67b08940233d235e46be`, `ev_a3c643870203e3829d4e1609570dd99c1621628bdb93d61d32fbfb4c6a24f96e` | Installed `Microsoft.PowerBI.Modeling.Engine.dll`, selected path-filter lambdas | CIL anchors show the path-length predicate and the `Item2`/`Item1` selectors. Equal-length pairs are not given a second sort key. |
| `ev_193ee52c6fb4c0124aab2e173c85c89faf687cf18a621d2fb1d97cdad5f9f2e3` | Installed `Microsoft.PowerBI.Modeling.Engine.dll`, selected `Pair<T>` | Direct mounted-package analysis confirms the generic pair type's fields and four declared methods; the detector projects this pair only after ordering by the scalar path length. |
| `ev_4a49c2fc34ae6983611a4fee093f94b63abab2ee904c4e6b592d57767461c885` | `Microsoft.PowerBI.Modeling.Contracts.dll` | `DataType` enum members. |
| `ev_5161e846f00f65c163a7d25a6c9c743ae6e157d0b054533052c96687999823bd` | `Microsoft.PowerBI.Modeling.Engine.dll` | `DetectionHelper` name-key methods, composite-key predicate, regex literals, delimiter set, and noise words. |
| `ev_4a89e9c28db70c7b4b2622d714920392ca2b565b9299e150d1fd492ef764e0bb` | `Microsoft.PowerBI.Modeling.Engine.dll` | Fast-detector key grouping, candidate-priority helpers, and cardinality/uniqueness/null APIs; its CIL anchors were expanded with the temporary local decoder. |
| `ev_3881722dc5402026f24a5fa78d98ead4b9710ae5b4919f30f108e56781c8f48b` | `Microsoft.PowerBI.Modeling.Engine.dll` | Selected detector and cardinality-query methods; CIL anchors confirm key eligibility, score computation, and the distinct-count/null-result accessors. |
| `ev_357fd938cfefceb6a60a6c444b2bbf2604bf806cae76a90decbfcb1f6402b61b` | `Microsoft.PowerBI.Modeling.Engine.dll` | `DataValidationConstants` static initializer includes the DAX query templates used for distinct count, row count, and null detection. |
| `ev_2937544cb88806fa8a32f65acbac0828453e264cff0563a535a69f1aeea3997e` | `Microsoft.PowerBI.Modeling.Engine.dll` | Fast-detector public method signatures, including its two-pass core. |
| `ev_00b5e0e6d523d05b46ab48116e5339b6fc729f85bca3ee1f07591f5511148b27` | `Microsoft.PowerBI.Modeling.Engine.dll` | `Detect` and `DetectCore` async state-machine call anchors and constants. |
| `ev_2f9ce59167571bebe975ee8cdc97e5ea1dcd6349bb3b03f22ab9f122a4a81c2f` | `Microsoft.PowerBI.Modeling.Engine.dll` | `pkColumns`/`fkColumns` role sets, saved-relationship mapping, and scoring members. |
| `ev_a9975afe0d32ed9d8df5e638b8f1a17cdd21f00535702f0b538da63115ab1af1` | `Microsoft.PowerBI.Modeler.dll` | `ModelEditor.SetKeyColumn`, `ColumnSubsystem.SetGroupByColumns`, and their Tabular API calls. |
| `ev_b89dc33d93576194cd4561ef9dd4f60b5c04dc9b498154b1e032edb048120f20` | Minerva directory, selected `modelView.html` and `scripts/desktopModelView.min.js` | Partial static model-view source analysis; the main script exceeded the remaining semantic graph result budget, but inspected text includes `KeyColumnBuilder` options, uniqueness validation, and the `setKeyColumn` schema-change path. |
| `ev_3d3caf60d9a88de48ceeef82215c909fd6e82ebb115d322335a54bba8e54b6d6` | Minerva directory, selected `scripts/desktopDialogHost.lazy-modeling-dialogs.min.js` | Focused static relationship-dialog analysis; 65 bundled modules and the `LazyModelingDialogModule` were retained. |
| `ev_0b709365fb2b9857be7d2316e29f89030509ba11d006d5e87a543277250ade57`, `ev_937439fe1e80909415035f28e47be04ba76654a8d74a18f67c0d0bf24574e9f0`, `ev_ea9f7ab552ab43e8c1441591a1709a605b76b7e75bee93d29545577cf990222a` | Installed `Microsoft.PowerBI.Modeling.Engine.dll`, selected detector result, `RelationshipEditor`, and `RelationshipEditorHelper` methods | Static CIL shows the detector returns candidate/key column pairs, the editor passes pair Item1/Item2 as From/To, and the default helper checks uniqueness/nulls on both ends. Automatic direction reverses endpoints when proposed To is not eligible as the one side; equal endpoint cardinalities choose Both cross-filtering. |
| `ev_920d8e25c4123c1116cee4db638961232924cffa3d859ddfb73ddd277eec795f` | Installed `Microsoft.PowerBI.Modeling.Engine.dll`, `RelationshipGraphEx` | Static CIL shows `CanCreateRelationship` runs basic relationship validation and active-path ambiguity checks. The default helper retries relationship settings and can fall back to an inactive proposal when graph admission fails. |
| `ev_96fdfd356ca451b98b9920050aa10fcae832a3540e0e3534b6ae26ef569d9a86`, `ev_43daefd90048afa07b678c1f2e400ae11edcf0217abed3c2d5d715778780530c` | Installed `Microsoft.PowerBI.Modeling.Engine.dll`, `RelationshipGraphEx`, `FilterGraph<T>`, and `PathNode` | `IsPathAmbiguous` builds forward and reverse filter-graph views, intersects reachable-table sets, and composes reversed paths. `PathNode.IsAmbiguous` compares the directness of the nonshared path segments; shared nodes are filtered out. |
| `ev_f800ffa436da0d5f39fa379cd11244b40ddc6f9253c7ad0dbe5c06a9f11af9ad`, `ev_3aeaaabba90dafd5800ddbaea3c79aee3169d7f9ef0d9974c244a4e9a327a304` | Installed `Microsoft.PowerBI.Modeling.Engine.dll`, selected DFS callback, path iterator, and ambiguity lambdas | The DFS callback replaces an existing route only when the new route is all-direct and the old one is not. `GetPathToRoot` yields current-to-root; `ToList` reverses it. `IsAmbiguous` applies `All(IsDirect)` to each path's nonshared nodes and compares the two results. |
| `ev_7a04705a4c214d99801ac8088cb5b9f6ab2d2e52981f88d089ed0f1d303ead66`, `ev_c92635acd6461906d255a400c0990ca02c416e909bfa2934920df0f4a6a2136f`, `ev_920d8e25c4123c1116cee4db638961232924cffa3d859ddfb73ddd277eec795f` | Installed `Microsoft.PowerBI.Modeling.Engine.dll`, `FilterGraph<T>.Add`, `RelationshipGraphEx` constructor/add methods, and graph builder | The graph stores `(target, isDirect)` pairs in a `HashSet`; it groups all relationships by `FromTable` into lists, then filters inactive rows during graph construction. Identical pairs collapse, while the same target with different directness remains present. |
| `ev_c7318fb29ded17db2a2de5b396e712e3182e3553678cfab0bb21fecb588fda55`, `ev_6ffa0727ec7b4b8f7cf08ec464a6b4bccd92a512b1b2bfa7f2213e43ff9a92b1` | Mounted Windows `mscorlib.dll` (SHA-256 `a8cae3d326f7d973ca79cba849939d4837ad18d507ef6d5f6ebab802b7fb157a`), selected `Dictionary<TKey,TValue>` methods | The dictionary enumerator scans entries by increasing index; `Insert` uses `count` for a new entry when there is no free-list slot, and `Resize` preserves those indices. The graph builder only adds source-table groups, so its dictionary traversal follows first insertion order. |
| `ev_b5545f62aa494c100df4539e8e8f72dd1ea4717c26e27b1cf2a76ded26b5fa4d`, `ev_355dfe695279185df18a0dbf6c855c469496278007794658d16bac590f277971` | Mounted Windows `System.Core.dll` (SHA-256 `06fbe25901c981f00f6dc823be375e1468cf6c05f000606bc93897732172fdd6`), selected `HashSet<T>` methods | The set enumerator scans slots by increasing index; `AddIfNotPresent` uses `m_lastIndex` when there is no free-list slot, and `SetCapacity` preserves slot indices. The graph build adds edges without removing them, preserving insertion order while exact duplicate `(target, isDirect)` pairs collapse. |
| `ev_e29f85c0a5742c27ab5a8daaa5c45418f79761ef7eb1c1f3d4fe717a6520900d`, `ev_970adfcc4f4fdf6acf4d1c56978c82e8e2ff73d6fff1c2bba846cae9274d5937`, `ev_55ba82fe0d04175e9b84e8dc4ca7b508dd39dd8f4a3053208548ae0278afe940`, `ev_4f62817e60b2fa142c6988c5b8fbe16dfa3405dac727a1a19fd7bc47d46bc59e`, `ev_cac62291820ef02ac664da7ce1c2d857741d562637f0b5bef7b4ef1d4a397c32` | Installed `Microsoft.PowerBI.Modeling.Engine.dll` (SHA-256 `466838efa60138e8bc685a07e3ee61063fd8ab8c104bd556107e6999736b128b`), `RelationshipGraphEx`, `TabularDataModel`, `ModelObjectConverter`, and the model-collection wrappers | The graph constructor enumerates `IDataModel.Relationships`; the Tabular adapter reads `Model.Relationships`, wraps it in model collections, then lazily converts each item through the converter's LINQ `Select` projection. The wrappers enumerate the underlying Analysis Services collection, preserving its sequence. |
| `ev_044188a59a7ce51f736093b83fd3d30d5c033c003cda199827535f6343a76aff`, `ev_3274d5361a13c4aa6559257c5761102f211f2536e79fc99f9280321075b46040`, `ev_6965583185de1ff4356de85b49bd4ee6d14c7727e5e548b3ec4d4052f2dff68e` | Installed `Microsoft.AnalysisServices.Server.Tabular.dll` (SHA-256 `d0cd90916ae3113e438b73f6cc71d6d05950f68593d988321407b838ecd91ec1`), `Model`, `RelationshipCollection`, and `NamedMetadataObjectCollection` | `Model.Relationships` returns its relationship collection; the collection derives from the named-metadata collection and uses an Analysis Services named collection as its backing store. |
| `ev_449bf6a6d8149b2305d96b3f9e2b976c9968654b645c170da9a7a53da1b06b34`, `ev_154460047590eabe4420f18e4e597de88581c4acc3731a9c464cd4fafa985122` | Installed `Microsoft.AnalysisServices.Server.Core.dll` (SHA-256 `0849d9fabb750f7c6975cae07edaf37b647f320c380437b50552e9a7dc0db95e`), `ModelComponentCollection`, `NamedComponentCollection`, and `ModelComponentEnumerator` | The collection tracks keys in `StringCollection` and values in a `Hashtable`; its enumerator traverses the key enumerator and looks up each value by key. Add/insert/remove operations update the ordered key list. |
| `ev_524f459afb4eec854c4605023a867d867a5752459f3d4d531e563b42fa8a91c3`, `ev_cfa8ea83e8af9933d23fa5c8fc89c0f6f61a571290f452d146b8b31324633b65`, `ev_9422249bef2396c3d79e169062c5e2657a0ed5af4fc227e0bb6b00c611290722` | Mounted Windows `System.dll` (SHA-256 `2b3c17c6208a0b4b6beb94e1a066f99ba06cdb2ea919479e99d47e8c6d96dc71`) and `mscorlib.dll` (SHA-256 `a8cae3d326f7d973ca79cba849939d4837ad18d507ef6d5f6ebab802b7fb157a`) | `StringCollection` wraps `ArrayList`; its `StringEnumerator` wraps the array-list enumerator. `ArrayListEnumeratorSimple.MoveNext` advances an integer index and reads `_items[index]`, establishing the ordered source sequence. |
| `ev_26ff59fe02a7a6194cdd2afcce3ec799c71f28800954cdd1d9a8403833a48a78`, `ev_e768f4a20faa33abbce78bd709a4c02e22904214b3768ccb0c5fc7f917999c0d`, `ev_297f20e95ac00068f1e759b72cb2601d63474f2e90e2888a7e57675d95666fa8`, `ev_bb3af16e72e8e6dc0f5f97940a85e025fb8427f910ca2497effce02f2c3c4680` | Minerva relationship-dialog module | Static traces for autodetection feedback, deletion confirmation, cardinality filters, and cross-filter direction filters. |
| `ev_b22899da14e5a636dc8451aa27367a0e55a5efc5a265937e14609d9a856a6bce`, `ev_2462e91727bb976d7cf74772574250d061b55e8ea7b7c0dab9afdc48114cb066` | Installed Minerva map bundle and UK TopoJSON, analyzed from the mounted package | Focused static JS parse: `MapVisuals` chunk and three modules; TopoJSON structure and keys. Partial selected-file analysis only; code was not executed. |

The retained REA evidence bundles are outside the repository:
`~/Library/Caches/codex-powerbi-rea/2.157.879.0/rea-evidence-bundle.json`
contains the 69 earlier package records;
`~/Library/Caches/codex-powerbi-rea/2.157.879.0/rea-evidence-bundle-20261019-relationship-details.json`
contains six relationship-detector records; and
`~/Library/Caches/codex-powerbi-rea/2.157.879.0/rea-evidence-bundle-20261019-restored-current.json`
contains the current 95-record merged snapshot, including the rerun detector
and Minerva records. During the investigation, an export replaced the previous
118-record contents of the relationship-details path with the six-record
supplement. No backup of that earlier export was found. The 69-record base
bundle remained intact, and the selected missing detector and Minerva analyses
were rerun and retained in the 95-record snapshot; this does not restore every
record from the overwritten export. The later
`~/Library/Caches/codex-powerbi-rea/2.157.879.0/rea-evidence-bundle-20261019-collection-order.json`
snapshot contains 355 session records, including the mounted .NET collection
evidence used to resolve graph traversal order.
The later
`~/Library/Caches/codex-powerbi-rea/2.157.879.0/rea-evidence-bundle-20261019-source-order.json`
snapshot contains 451 session records and adds the installed model adapter,
Analysis Services collection, and .NET Framework array-list enumerator evidence
used to trace relationship input order.

## Findings

### Data-view sort and filter query bridge

REA inspection of `Microsoft.PowerBI.Client.Windows.dll` (SHA-256
`f0dd0953a7e647bbda3b606fcc28712dbfd05d1d6c8afa5e1ac0d2da3501c347`)
shows `DataSourceHostService` holding a `sortFilterColumns` dictionary keyed
by table name. `GetQueryInfo` calls `GetColumnSortInfos` and
`GetColumnFilterInfos`, then stores their results as `ModelQueryInfo.OrderBy`
and `.Filters`. The corresponding metadata records expose column plus sort
direction, or column plus filter. This establishes that the host passes
table-specific sort/filter state into data-view queries.

The local Data view now supports one-column ascending/descending sorting of
all loaded rows before applying its 500-row page. That behavior is a bounded
reconstruction of the query bridge, not an observed reproduction of the
Power BI header gesture. The inspection did not establish multi-column UI
behavior, sort tie rules, blank/error ordering, locale collation, or the
filter editor's interaction semantics. It also did not establish cell,
column, or table copy behavior. Static evidence is in
`ev_778d983469bbd44a163648b0be7ec6cecdd2153d526474cd496300c0055e1b08` and
`ev_cece080def8c568eeb73eb456843ea0359ca7b2f1405196ff596ee5605af82dd`.

**Observed in the shipped assemblies:** the modeler exposes relationship
creation, addition, deletion, and cleanup methods. Its metadata includes the
`AutoDetected_` prefix. The modeling engine exposes detector operations such as
`Detect`, `GetColumnsByKey`, `GetActualPKColumn`, and
`RequestColumnCardinalitiesInBatch`; helper names cover normalized column names,
key-like names, possible keys, related table pairs, and graph traversal. CIL
anchors show the key normalizer uses camel-case, parenthetical-comment, digit,
and noise-word processing. Its literals are `[A-Z]([a-z]+|[A-Z]*$)`,
`\([^\(//)]*\)`, and `[0-9]`; its split delimiter set covers the listed
ASCII punctuation characters. The observed noise words are `name`, `id`,
`key`, `code`, `pk`, and `fk`. The fast detector tracks primary and foreign-key
columns, related columns and tables, checked pairs, and asynchronously requests
column cardinalities in batches. Other helper calls examine key eligibility,
uniqueness, nulls, and relationship paths. These are static findings, not a
complete reconstruction of its ranking logic. `CanHaveRelationship` checks
both columns as possible keys and compares their `RelationshipKeyType` values;
that enum separates `Int` and `Double`, and the `Variant` data type resolves to
`InvalidKey`. Decoding the retained switch body together with the two enum
constant tables gives this mapping: `Binary` and `Variant` → `InvalidKey`,
`Boolean` → `Boolean`, `Currency` and `Number` → `Double`, `Date` → `Date`,
`DateTime` → `DateTime`, `Time` → `Time`, `WholeNumber` → `Int`, and `Text` →
`String`. This is a static CIL-derived mapping, not a runtime observation.
`GetColumnsByKey` applies an additional `IsNumericOrString` predicate. Its CIL
accepts enum values 1 through 3, which the enum field order identifies as
`String`, `Int`, and `Double`; Boolean, Date, DateTime, and Time columns are
therefore excluded even though the type switch assigns them distinct key types.
Analytics Studio's autodetector now admits only text, whole-number, and decimal
columns, rejects whole-number/decimal cross-pairs, and does not treat `any` as
a wildcard. `Currency` is not a model type currently exposed by Analytics
Studio.

The `Detect` state machine calls `DetectCore` twice, first with its key-name
normalization flag false and then true, concatenates the results, and sends
them through the shared filter/sort pass. `GetColumnsByKey` scans nonempty
import tables and accepts columns in state 1 with a name, excluding calculated
columns, key types outside String/Int/Double, and columns with nonempty
related-column `GroupByColumns` metadata. It rejects a key group whose entire
name is one of
the configured noise words, so a literal `ID` key is not matched directly; the
normalized pass can instead fall back to the table name when cleanup leaves no
column-name words. The table-name fallback is shared by both passes whenever
splitting leaves no words.

`DetectCore` enumerates key groups, asks
`GetPrioritizedPKColumnsWithTheSameKey` for eligible primary-key columns, then
scans the group's columns for each one. The selector keeps an explicitly marked
key or a unique, null-free column, then orders by
`distinct cardinality * 10 + (not FK ? 1 : 0) + (PK ? 2 : 0)`. The detector's
`MapExistingRelationships` populates `fkColumns` and `pkColumns` through
`AddRelationshipColumnPair`; each accepted suggestion adds its candidate
column as FK and selected one-side column as PK. Analytics Studio rebuilds
these role sets from saved relationship endpoints and earlier suggestions,
then uses the same score. It also persists a table-level `key_column` and
passes it to the detector: a marked key bypasses the unique-and-null-free
eligibility gate, while distinct cardinality and relationship roles still
determine the score. Equal scores retain key-group member order. The local key
metadata affects relationship autodetection only; it does not implement
featured-table data-search behavior. Analytics Studio also persists
`GroupByColumns` metadata and excludes marked columns from relationship key
discovery; that metadata does not yet affect visual grouping, filters, or DAX
evaluation.

The key-group statistics come from DAX query templates that return
`DISTINCTCOUNT` for each column, `COUNTROWS` for its table, and
`NOT ISEMPTY(FILTER(table, ISBLANK(column)))` for the null flag. The helper
defines uniqueness as distinct count equaling row count and reads null
presence separately (`ev_357fd938cfefceb6a60a6c444b2bbf2604bf806cae76a90decbfcb1f6402b61b`).
Microsoft documents DAX model blanks for nulls, blank values, empty cells, and
missing values, while noting that empty strings and blanks can differ by
operation ([Power BI data types](https://learn.microsoft.com/en-us/power-bi/connect-data/desktop-data-types),
[`BLANK`](https://learn.microsoft.com/en-us/dax/blank-function-dax),
[`DISTINCTCOUNT`](https://learn.microsoft.com/en-us/dax/distinctcount-function-dax)).
Analytics Studio therefore profiles zero-length text as blank during
relationship autodetection. This is a DAX-profile inference; the installed
Desktop runtime and connector-specific source import behavior remain
unverified. REA could not inspect `Microsoft.MashupEngine.Library45.dll`
member metadata because it exceeded the 64 MiB representation budget.

Microsoft's [Power BI data-types documentation](https://learn.microsoft.com/en-us/power-bi/transform/desktop-data-types)
also describes the loaded model as case-insensitive and says trailing spaces
are removed or trimmed while leading spaces remain. Analytics Studio's shared
relationship key comparer now removes trailing ASCII spaces, then applies
Unicode case-folding. This affects relationship matching and one-side
uniqueness as well as the detector profile; it does not trim leading spaces,
tabs, or other whitespace. The precise locale/collation behavior remains
unmodeled.

**Key-metadata scope follow-up:** the Modeling Contracts `IColumn` interface
exposes `get_IsKey` without a setter, while the separate Tabular `Column` API
has `set_IsKey(Boolean)`. The Modeler exposes `SetKeyColumn`; the selected
Minerva Model-view bundle includes a `setKeyColumn` schema-change path and
confirmation text explaining that clearing a key removes featured-table
status. The bundled Model-view source's `getKeyColumnOptions` exposes a
no-key option and otherwise lists only columns with the model `Data` type; its
strings describe key columns as unique and report a duplicate-value validation
error. This is a featured-table key property in Power BI; the local
implementation stores its key-column signal for relationship autodetection but
does not implement featured-table data search, row labels, or the full
featured-table experience. The local Model view offers loaded source columns
and checks their values for uniqueness before saving the marker. The Modeler also exposes
`SetGroupByColumns`, which writes `RelatedColumnDetails.GroupByColumns`; the
detector excludes columns with a nonempty list. Analytics Studio stores that
property in project format v81 and exposes a local Model-view checklist editor
for loaded source columns. The inspected target source does not establish a
generic user-facing editor. The local property currently affects relationship
autodetection only. REA Evidence
`ev_a9975afe0d32ed9d8df5e638b8f1a17cdd21f00535702f0b538da63115ab1af1` is bound
to Modeler SHA-256
`c5d5bb827acc2c634eb0993a70dd4f64b1641b86dff67baa1bed188536803e1d`; Minerva
source analysis is in
`ev_b89dc33d93576194cd4561ef9dd4f60b5c04dc9b498154b1e032edb048120f20`.

The key-grouping CIL contains two count gates with the literal value 30. A
per-table `KeyCounter` increments before a `>= 30` branch, so only the first 29
eligible columns for a key enter that table's key group. A second counter keys
groups by the comma-joined distinct participating table names; counts through
30 are admitted and later groups with the same table-name signature are
skipped. Both gates run in each of the detector's literal and normalized
passes. Analytics Studio now applies those two limits when building key groups.
`MapExistingRelationships` records existing direct table pairs, and
`AreRelated` checks that pair set rather than a transitive closure. The final
`FilterAndSortColumnPairs` pass computes candidate path lengths over existing
and proposed relationships, sorts by path length, and expands the allowed
length from 1 through the caller's limit of 4, stopping when the requested
table set is connected or the limit is reached. The recorded methods are
`GetColumnPairsPathLengths`, `MarkTableRelationships`, `AreTablesConnected`, and
`TraverseReachableTables`; their metadata tokens are build-local to the
documented assembly hash. Power BI's `Detect` request callback maps nonempty
`RelationshipDetectionRequest.Tables` to `tablesToBeConnected` and skips this
pass when that set is null or empty. Analytics Studio preserves its global
manual autodetect path and now offers an optional table-scope action. The scoped
action traverses saved relationships and proposed candidates in both
directions, admits proposals in path-length order through length 4, and stops
once the selected tables connect. The native pass orders by the integer path
length and then projects the original pair; LINQ's stable `OrderBy` preserves
detector discovery order for equal lengths. The local detector uses the same
stable tie behavior. The native connection check returns true when fewer than
two tables are requested, so a single-table low-level scope stops at the first
path threshold; Analytics Studio's visible scope picker still asks the user to
select at least two tables.
This implements statically observed core request behavior; the inspected
evidence does not establish how Power BI exposes that request in its UI.
`HasIdenticalSchema` also rejects a candidate if both tables have equal column
counts and each user column has a same-name, same-data-type counterpart.
`UserColumns` excludes the Tabular `RowNumber` column type. Analytics Studio now
skips candidates with identical loaded names and types; its model does not
represent a separate RowNumber column. The traversal follows existing
relationship records in both directions without an observed active-state
check. The detector's prioritized-key predicate admits an `IsKey` column or a
column that is unique and has no nulls. The separate
`CanBeOneSideOfRelationship` helper accepts missing cardinality information;
when it exists, the helper requires uniqueness and no nulls. Neither inspected
path has a separate nonblank-value condition. The installed cardinality query
uses `DISTINCTCOUNT`, `COUNTROWS`, and an `ISBLANK` scan. Analytics Studio now
maps zero-length text to the blank category in this detector profile, based on
DAX's documented model blank handling. Other local relationship operations
still retain a distinct key category for `""`; text values differing only by
trailing ASCII spaces now share a key. This is an inference: static
CIL and product documentation do not establish how every connector preserves
empty text in the imported model or how the profile query reports it at runtime.

**Inferred for Analytics Studio:** the first local feature slice adds an
**Autodetect** action to the relationship dialog. It proposes links between
loaded tables using normalized names, compatible model types, and one-side
uniqueness without nulls. It derives uniqueness, null presence, and cardinality
from loaded values, then evaluates exact key groups in discovery order and
ranks eligible one-side columns with the native cardinality-and-role score,
rebuilding its PK/FK role sets from saved links and earlier suggestions. The
dialog preserves global autodetection and adds an optional selected-table scope
that invokes the path-length pass. Equal-path proposals retain discovery order,
matching the native stable `OrderBy` on path length; the native detector does
not use the pair as a secondary sort key.
Runtime and manual UI acceptance of this new scoped action has not been
recorded. The detector does not require
the two columns to share sampled values: REA's retained
detector call flow centers on matching key groups and batched
cardinality/uniqueness checks, and the local model can represent unmatched
relationship members. Its key
normalization uses both recovered passes: literal camel/split names, then
comment, number, delimiter, and noise-word cleanup; either pass falls back to
the table name when splitting leaves no words. A literal `ID`-to-`ID` key is
filtered, while an ID-only column may match a base key through table-name
fallback. The detector constructs each pair as candidate column then selected
primary-key column. The installed `RelationshipEditor.GetRelationshipCandidates`
passes Item1/Item2 as `fromColumn`/`toColumn` to its default relationship
builder, which checks uniqueness and nulls on both ends. When automatic
direction is enabled and the proposed To end is not eligible as the one side,
the helper reverses endpoints and defaults to Many-to-One. For the common
non-unique candidate and unique key case, the suggestion remains Many-to-One
with the candidate as From and key as To; if both endpoints are unique and
null-free, it is One-to-One. The helper chooses Both cross-filtering when both
endpoint cardinalities match, so the detected One-to-One case uses Both while
Many-to-One uses Single. The Minerva action uses the resulting `fromColumnUrn`
and `toColumnUrn` directly. Analytics Studio mirrors this endpoint and
cross-filter default. The branch interpretation is based on static CIL, and
relationship admission is not runtime-verified. The native pair construction
and editor/helper CIL are retained under
`ev_0b709365fb2b9857be7d2316e29f89030509ba11d006d5e87a543277250ade57`,
`ev_937439fe1e80909415035f28e47be04ba76654a8d74a18f67c0d0bf24574e9f0`, and
`ev_ea9f7ab552ab43e8c1441591a1709a605b76b7e75bee93d29545577cf990222a`; the
Minerva source is `ev_3d3caf60d9a88de48ceeef82215c909fd6e82ebb115d322335a54bba8e54b6d6`.
The installed graph helper's `CanCreateRelationship` checks basic endpoint
validity and active filter-path ambiguity. `IsPathAmbiguous` composes paths
through shared reachable tables. `PathNode.IsAmbiguous` then filters out nodes
shared by both paths and compares whether each remaining path segment consists
entirely of direct edges. The separate `AllDirect` flag is used by DFS to keep
an all-direct route when a table is reached by both a direct and indirect path.
`PathNode` also preserves edge directness while paths are traversed, reversed,
and combined. The default helper retries cardinality, filter direction, and
cross-filter behavior before it may deactivate a proposal. Analytics Studio
now builds both oriented graphs, retains the native directness labels in its
DFS paths, retains edges with the same target but different directness, and
preserves inactive saved relationships through source-table grouping before
filtering them from the active graph,
prefers an all-direct route per table, composes shared paths, applies the
Single/Both admission checks, and follows the recovered default retry order. It
also omits candidates with no unique, null-free endpoint. This is a static-CIL
interpretation. The mounted .NET Framework CIL shows dictionary and HashSet
enumerators scan backing arrays by increasing index, while new graph entries use
the next index when there are no deletions and resize preserves those indices;
the graph-building path only adds groups and edges. The installed model adapter
also enumerates `IDataModel.Relationships` from the Analysis Services
`RelationshipCollection`; its backing collection enumerates an ordered
`StringCollection` key list, and the conversion layer uses a sequence-preserving
LINQ projection. Analytics Studio's relationship editor appends new model rows,
project normalization retains array order, and the detector does not sort the
saved relationships, so its graph receives the same order for Analytics
Studio-authored models. External PBIX relationship-order translation is outside
the supported project format. Connector-specific empty-text import behavior
and target-runtime suggestion activity remain unverified. CIL evidence is
`ev_920d8e25c4123c1116cee4db638961232924cffa3d859ddfb73ddd277eec795f` for
`RelationshipGraphEx`, `ev_96fdfd356ca451b98b9920050aa10fcae832a3540e0e3534b6ae26ef569d9a86`
and `ev_43daefd90048afa07b678c1f2e400ae11edcf0217abed3c2d5d715778780530c`
for path composition, `ev_f800ffa436da0d5f39fa379cd11244b40ddc6f9253c7ad0dbe5c06a9f11af9ad`
for the DFS callback and path iterator, `ev_3aeaaabba90dafd5800ddbaea3c79aee3169d7f9ef0d9974c244a4e9a327a304`
for the ambiguity predicates, `ev_7a04705a4c214d99801ac8088cb5b9f6ab2d2e52981f88d089ed0f1d303ead66`
and `ev_c92635acd6461906d255a400c0990ca02c416e909bfa2934920df0f4a6a2136f` for
edge identity and grouping, and `ev_ea9f7ab552ab43e8c1441591a1709a605b76b7e75bee93d29545577cf990222a`
for the default helper.
The detector skips table pairs with a saved direct relationship or an identical
loaded schema, and leaves suggestions in the dialog for review before Save
changes the project.
It also skips zero-row tables before key grouping, matching `GetColumnsByKey`'s
nonempty-table gate. A saved explicit key column bypasses the detector's
unique-and-null-free primary-candidate gate, matching its `IsKey` condition;
the local key marker is stored in project format v82. The Model-view source
analysis for this property is partial, and the local implementation covers
only the detector signal and uniqueness validation.

This is a local, review-first design informed by static clues. It is not a claim
that the implementation reproduces Power BI's detector; the local table
`key_column` models the explicit key eligibility signal but not the rest of
featured-table behavior, and empty-text versus blank cardinality uses a
runtime-unverified DAX-profile approximation. The local `GroupByColumns`
property models the detected exclusion rule but not its complete Tabular
semantics.

**Model-view source follow-up:** the extracted `modelView.html` references
`desktopModelView.min.js`, which has file SHA-256
`5921d48cdd98f0545652fbfac1c61092e1cd48de158f48b2e378035d1358e837`. REA
analyzed that page and script as inert text under Evidence
`ev_b89dc33d93576194cd4561ef9dd4f60b5c04dc9b498154b1e032edb048120f20`. The
script's semantic graph exceeded the parent's remaining result budget; its
static and module facts were retained, while 2,602 inventoried files remained
outside this selected analysis. This confirms the shipped Model-view page and
its bundle identity, not runtime diagram interactions or a complete UI
reconstruction. Analytics Studio previously showed table cards and a text list
of relationships. It now has a switchable local relationship diagram that
draws saved structured links with active state, cardinality, and filter
direction, while keeping its existing relationship list and editor. This is a
bounded local feature increment, not evidence of full Power BI diagram parity.

**Table-list search follow-up:** REA's focused parse of the same installed
`desktopModelView.min.js` retained analysis Evidence
`ev_e274dde882ffe2294cfc3d2dec387d323bbdf6439c51671bb566db909bf20e4a` and
inspection Evidence
`ev_ebea5b948b71e3869865c1bd0e9a2817d113f0774d028f9b6b8a2e90b80c9779`. The
selected file's SHA-256 remained
`5921d48cdd98f0545652fbfac1c61092e1cd48de158f48b2e378035d1358e837`; REA
parsed 1,626,789 AST nodes, but the semantic graph was partial and the script
was not executed. A `Search tables` localization string was found. A locale
string alone does not prove the control is visible or establish its runtime
behavior, so this is not evidence of Power BI search parity. The local
Analytics Studio Table list now has a transient name search; its tested scope
is table/display names and loaded column names, not row filtering or the
featured-table data-search experience.

The local app's main-display smoke caught a separate rendering issue: the
search control inherited a dark host style and its placeholder/border were
faint against the intended light surface. Analytics Studio now sets explicit
text, placeholder, background, selection, and focus-border colors. Local
regressions measure the placeholder at 4.80:1 and the normal/focused borders
at 3.59:1 and 5.07:1. The captured local app state is
[`model-table-list-search-contrast.png`](verification-artifacts/model-table-list-search-contrast.png).
This is evidence about Analytics Studio's rendering only. The Windows Power BI
window remained unavailable for interactive comparison, so target UI behavior
and visual parity are still open.

**Relationship-dialog flow follow-up:** REA analyzed the installed
`scripts/desktopDialogHost.lazy-modeling-dialogs.min.js` (file SHA-256
`9aeceaf59c7c79d2467d4ea45ab9941d69dc052deccc4c2231d82a90ea79b0c1`) as inert
JavaScript. The selected source contains the `LazyModelingDialogModule`
(Webpack module key `37735`). Static references associate the module with an
autodetection notice that reports the found count or no-results case, and with
an OK/Cancel confirmation before deleting relationships. The source also
constructs its selection model in multi-select mode and gathers selected rows
into one delete request. REA traces
`ev_26ff59fe02a7a6194cdd2afcce3ec799c71f28800954cdd1d9a8403833a48a78` and
`ev_e768f4a20faa33abbce78bd709a4c02e22904214b3768ccb0c5fc7f917999c0d` retain
the corresponding graph paths. Analytics Studio now presents the autodetect
result and confirms staged deletion before changing the dialog's relationship
list in one batch; its final project save remains user-controlled. This one-file analysis
is partial: 2,603 inventoried files were outside the selected scope, dynamic
relationships remain unknown, and no Power BI code was executed.

**Relationship-list filtering follow-up:** the same module's filter predicate
allows any selected value within a filter category; when cardinality and
cross-filter direction are both selected, both categories must match. The
installed UI exposes `ManyToOne`, `OneToOne`, and `OneToMany`; it adds
`ManyToMany` when the model reports support. The filter values map directly to
Analytics Studio's `many_to_one`, `one_to_one`, `one_to_many`, and
`many_to_many` forms. Its `OneDirection` and `BothDirections` values map to
local `single` and `both`. Analytics Studio's checkable filters use the same
within-category OR and across-category AND rule, and its cardinality options
now follow the native order. REA traces
`ev_297f20e95ac00068f1e759b72cb2601d63474f2e90e2888a7e57675d95666fa8` and
`ev_bb3af16e72e8e6dc0f5f97940a85e025fb8427f910ca2497effce02f2c3c4680`
associate the filter labels with the same static module. This is static
artifact evidence, not runtime behavior.

**Relationship-list sorting follow-up:** the data-source sorter in the selected
module accepts `fromtablecolumn`, `relationship`, `totablecolumn`, and `active`
keys. `relationship` sorts on the concatenated cardinality and cross-filter
behavior enum strings; `fromtablecolumn` and `totablecolumn` use the respective
column `displayName` lowercased, and `active` uses the Boolean text `true` or
`false`. The default is ascending `fromtablecolumn`. Analytics Studio now
offers those four sort dimensions and ascending/descending order from the
existing relationship list. Its sort keys now use the endpoint column name
alone, the matching PascalCase cardinality/direction enum strings, and Boolean
text for active state. Sorting changes the displayed order only and keeps the
underlying saved relationship sequence intact. Evidence is the same selected
source analysis above, bound to file SHA-256
`9aeceaf59c7c79d2467d4ea45ab9941d69dc052deccc4c2231d82a90ea79b0c1`; no Power
BI runtime interaction was observed.

## Limits and open questions

REA's managed provider reads assembly metadata and CIL anchors; it does not load
the assemblies into a CLR, decompile C# source, or execute Power BI. The
screenshots establish visible app state, not a trace of its relationship
detection behavior. The final path filter is skipped for null/empty scope;
Analytics Studio's global action follows that path, while its optional scoped
action provides the selected target set. The detector profile currently maps
zero-length text to blank based on DAX documentation; connector-specific import
behavior, target-runtime profile results, and remaining column-role edge cases
remain open. Analytics Studio now persists the `GroupByColumns`
exclusion metadata and applies it during relationship key grouping; it does not
implement the property's visual, filter, or DAX semantics.
Several large client and Mashup assemblies also exceeded REA's
64 MiB result representation limit during member projection, so those areas
were not fully inspected. The Minerva analysis is also incomplete: 2,586
inventoried Minerva files were outside the selected source set; static graph
coverage is partial, dynamic paths remain unresolved, and static references do
not prove that code runs. REA's optional Wakaru source-recovery provider is
not configured, and a broad relationship-feature trace exceeded the MCP
response budget. The model-view bundle is available as retained static facts
and original minified bytes only. The installed files do make Power BI's local web UI
code available for investigation, but a package inventory and partial static
analysis do not amount to a complete behavioral reverse engineering. The
current implementation covers only relationship suggestions; it does not
reproduce Power BI as a whole.

**Local verification status (2026-10-19):** the REA-guided detector, dialog,
metadata, Model diagram, and migration regression checks pass with the complete
Analytics Studio test suite. Exact command/results and remaining runtime
acceptance items are tracked in
[`POWER_BI_FUNCTIONALITY_WORK_LOG.md`](../POWER_BI_FUNCTIONALITY_WORK_LOG.md).

## Import and Power Query editor evidence (2026-10-20)

REA inspected the installed `Microsoft.Mashup.Client.Desktop.UI.dll`
(`b6ae4a066dd61576edddaf4cc6911cdbd8c6d90157b918a5d15d3427526bc904`). Its
managed metadata exposes separate commit and cancel labels, query add/update
flows, script validation and commit services, modeless editing-session
contracts, and editor feature settings. In particular, query editing is a
staged flow with an explicit commit boundary. This supports staging imported
sources in the local editor and committing on **Close & Apply**; metadata alone
does not establish the exact live UI sequence or connector-specific behavior.

The related Minerva desktop-dialog-host analysis selected the modeling mashup
editor host and proxy navigator scripts, but the recovered graph is partial and
static. A trace for the literal **Close & Apply** label did not resolve in that
partial graph; this is not evidence that the feature is absent. No Power BI
runtime interaction was recorded. The 44-record REA evidence export is
`/Users/armaan/Library/Caches/codex-powerbi-rea/2.157.879.0/rea-evidence-bundle-20261020-import-transform.json`.

Analytics Studio now presents **Load** and **Transform data** after file,
folder, SQL Server, OData, and Web previews. Transform stages the source in its
Power Query editor and applies it only after the user commits; cancel preserves
the project. Regression coverage includes fresh and existing projects,
connector staging, cancellation, and editor palette behavior. The local M
engine remains a partial implementation and does not provide general Mashup
runtime compatibility.

## Live DAX-editor observation (2026-10-20)

With the user's authorization to use the main display, Power BI Desktop was
opened with the supplied VAT workbook in memory. Selecting **New measure** and
typing `SUM(` showed the function signature `SUM(ColumnName)`, the help text
“Adds all the numbers in a column,” and an IntelliSense list of loaded fields,
including `Table 3 (VAT 5%)[Sales]`. The measure draft was canceled without
saving; no workbook or project was changed. REA captured the editor as window
12568, evidence
`ev_b82caa80e075bb1ec249440800a00ec89f938a93fd4b7c3ebe9648763e11929d`.
The 8-record evidence bundle is retained at
[`docs/verification-artifacts/rea-powerbi-live-dax-20261020.json`](verification-artifacts/rea-powerbi-live-dax-20261020.json).

The observed process was Parallels' macOS `WinAppHelper` proxy, not the Windows
`PBIDesktop.exe` engine. REA's native observer exposed only the top-level window
and no child controls. This is direct visual evidence of the DAX help UI, not
evidence about Power BI's calculation engine or internal control flow. A local
Analytics Studio dialog separately previewed `SUM([Sales])` as 350 on a
synthetic in-memory sample. The two checks used different datasets and did not
evaluate the same committed expression; numerical parity remains unverified.

The final local Analytics Studio suite passed **941 tests and 715 subtests**;
focused DAX completion tests, compile, lint, and whitespace checks passed.
Power Query live comparison, model-view parity, chart-resize comparison, and
full DAX/Tabular and Mashup/M runtime parity remain open.

## Iteration 41 live VAT comparison (2026-10-20)

The same Vat File -Aug 2026.xlsx, worksheet VAT 5%, was compared in Power BI
Desktop and Analytics Studio. Power BI DAX Query View returned 573 raw rows
and SUM(Value) = 1,498,307.26; its predicate Particulars <> "Grand Total"
returned 572 rows and 749,153.63. Analytics Studio's local parser/evaluator
matched both displayed totals to cents. The workbook contains a footer row
labelled Grand Total that repeats the sum of the 572 detail rows, explaining
the apparent double total.

Analytics Studio's Power Query editor created
Table.SelectRows(Source, each [#"Particulars"] <> "Grand Total") and previewed
572 rows. Its Data view funnel filter also displayed 572 rows and was cleared
to restore 573. The Data view dialog explicitly says this preview filter does
not change the loaded table, report calculations, or saved Power Query steps.
Power BI's temporary filter was removed; neither project nor source workbook
was saved.

Screenshots and the five-record REA observation bundle are linked from
[iter41-vat-comparison.md](verification-artifacts/iter41-vat-comparison.md).
REA exposed only the selected Parallels host window, not its child controls or
query cells. The screenshot therefore establishes visible results, not a
calculation-engine trace. Power BI's field pane also lists VAT 5% alongside
Table 3 (VAT 5%); only the latter was queried, leaving the other table
unverified.

The complete local application suite passed **941 tests and 715 subtests**;
compileall and git diff --check passed. This verifies one workbook and one
footer exclusion only. It does not establish saved report-visual behavior,
full DAX/Tabular or Mashup parity, or broader Power BI compatibility.

## Iteration 42 Power Query worksheet comparison (2026-10-20)

Power Query Editor showed two distinct queries sourced from the same workbook.
The query named `VAT 5%` has the applied steps `Source`, `Navigation`,
`Promoted Headers`, and `Changed Type`; it reports 14 columns and 622 rows.
Its first promoted column is the worksheet's company title,
`Loops Fire & Safety Equipment LLC-New (2020)`, followed by generic names such
as `Column2`. It therefore represents the worksheet preamble as table data and
does not have the intended transaction headers.

`Table 3 (VAT 5%)` is a separate query. It reports 14 columns and 573 rows and
has `FilterNullAndWhitespace`, `Removed Bottom Rows`, `Removed Top Rows`,
`Promoted Headers`, and `Changed Type` after navigation. Its headers include
`Date`, `Particulars`, and `Value`. The live UI inspection showed both queries
in the same workbook session. The retained screenshot excerpts show the step
names but do not preserve the Source path or numeric arguments for the row
removals. The clean output's headers and row count are consistent with removing
the preamble before promoting its actual row-12 headers. The `Grand Total`
footer remains in the resulting 573-row table.

The local Excel importer already detects row 12, returns the same 14-column,
573-row shape, and retains the `Grand Total` row. Excluding that footer is a
separate, explicit data-cleaning decision: it produces 572 detail rows and
`SUM(Value) = 749,153.63`; the unfiltered 573-row sum remains
`1,498,307.26` because the footer repeats the detail sum. The importer does not
silently discard the footer.

The workbook package's `VAT 5%` worksheet XML declares dimension `A1:N623`,
while its last populated cells are on row 585 and the local cell parser returns
the 573 rows from worksheet rows 13–585. The raw Power BI count of 622 is
consistent with promoting row 1 and retaining the worksheet extent through
row 623. Together with its visible lack of cleanup steps, this is a strong
explanation for the count difference: the raw path retains ten remaining
preamble rows, row 12's real header as data, and 38 trailing blank rows. This
is an inference from the workbook XML, screenshot-visible query steps, and
counts; it is not a trace of Power BI's internal Excel range enumeration.

This follow-up adds an import-preview notice when the selected Excel header row
is below row 1: `Using worksheet row 12 as column names; rows 1–11 are excluded
from the imported table.` The parser attaches the notice for both `.xlsx/.xlsm`
and legacy `.xls`; the preview displays it. The notice describes header
detection, not an applied filter or a change to the table's remaining rows.

Power Query screenshot excerpts:

- The separate raw worksheet query: [promoted title and generic columns](verification-artifacts/powerbi-vat5-worksheet-query-header-iter42-20261020.png), [applied steps](verification-artifacts/powerbi-vat5-worksheet-query-steps-iter42-20261020.png), and [622-row status](verification-artifacts/powerbi-vat5-worksheet-query-count-iter42-20261020.png).
- The cleaned query: [transaction headers](verification-artifacts/powerbi-vat5-clean-query-header-iter42-20261020.png), [applied steps](verification-artifacts/powerbi-vat5-clean-query-steps-iter42-20261020.png), and [573-row status](verification-artifacts/powerbi-vat5-clean-query-count-iter42-20261020.png).

REA's read-only native observation selected the already-running Parallels
`WinAppHelper` window (evidence `ev_a086fff1bb5133f2c0306a82f128f9a221c92837125028a3097ba2d9303fa548`).
It exposed only the top-level window, not Power BI's child controls, query
steps, or row values. Those details above come from the captured Power Query
screenshots and direct visual inspection; they are not REA accessibility-tree
or engine-trace results.

A later read-only REA screenshot of the same running Power BI Query View
(`ev_216373abd0f419fe9c53836a09f4bf5a1975f272ea3b832e9992ceaf3fc77fcc`)
visibly contains the `EVALUATE` expression and displayed 573 / 1,498,307.26
and 572 / 749,153.63 results. The accessibility capture still contains only
its top-level node, so these remain screenshot observations rather than
extracted query cells or a semantic-engine trace. No action was performed.

The Power Query Editor was closed without applying edits. Power BI was returned
to its original DAX Query View, with both projects and the source workbook left
unsaved. A new asynchronous Excel preview regression now exercises a generated
11-row preamble workbook and checks the detected row, notice, footer retention,
and clicks the Load/Transform buttons to confirm matching action candidates. The
project suite passed **944 tests and 717 subtests in 37.11 seconds** using
default `pytest -q` discovery; `pytest.ini` scopes collection to `tests/`.
`compileall` and `git diff --check` passed. This verifies the Excel header
notice and its preview display, not general Excel query equivalence, full M or
DAX compatibility, saved report behavior, or overall Power BI parity.

## Iteration 43 read-only window identity check (2026-10-20)

REA captured the already-running `Untitled - Power BI Desktop` Parallels
`WinAppHelper` window again as evidence
`ev_e89208d6d56663131f2c7192f147e7ff545f2939f4aff64665a005f4dc07ea09`.
The accessibility result contains only the top-level window with zero exposed
children. This confirms the selected window identity but adds no evidence about
Power Query controls, filters, calculations, or model behavior. No Power BI
action was performed, and the open project was left as-is.

## Iteration 50 Power Query sparse-row formulas (2026-10-21)

REA selected each applied step in the already-open Power Query Editor for
Power BI Desktop 2.157.879.0 and recorded its visible formula-bar expression.
The captures directly observed the helper
`each List.Select(_, each _ <> null and (not (_ is text) or Text.Trim(_) <> ""))`,
then `Table.RemoveLastN` for the bottom boundary, `Table.Skip` for the top
boundary, and
`Table.PromoteHeaders(#"Removed Top Rows", [PromoteAllScalars=true])`. The
bottom step showed **14 columns, 585 rows**; the top step showed **14 columns,
574 rows**; promoted headers showed **14 columns, 573 rows**. Evidence IDs,
hashes, and the original selected-step screenshots are in
[`rea-powerbi-vat-sparse-steps-iter50.json`](verification-artifacts/rea-powerbi-vat-sparse-steps-iter50.json):
[helper](verification-artifacts/powerbi-vat-helper-filter-null-whitespace-iter50.png),
[bottom trim](verification-artifacts/powerbi-vat-removed-bottom-rows-iter50.png),
[top trim](verification-artifacts/powerbi-vat-removed-top-rows-iter50.png),
and [promoted headers](verification-artifacts/powerbi-vat-promoted-headers-iter50.png).

This is direct visible evidence for the selected formula-bar expressions, not
a full Advanced Editor capture or a trace of Microsoft's Mashup engine. The
source/navigation expression and the later `Changed Type` expression were not
captured. The Power BI workbook/project was not changed or saved.

The same sparse helper and edge predicates were replayed locally against the
supplied VAT workbook. With the explicit row-1 Excel candidate, local counts
were **622 → 584 → 574 → 573** (bottom trim → top trim → promote headers),
producing **573 rows × 14 columns**. Power BI's observed intermediate counts
start at 585, so the bottom-trim boundary differs by one row. An extra sparse
row in Power BI source/navigation that is removed by the later top trim could
explain this, but that is an inference because the Navigation expression was
not captured. The
final shape, column names, and `Grand Total` values (`Sales` 749153.63,
`VAT-5%` 37406.97) match the observed workbook expectations, but the captures
do not establish cell-for-cell equality against Power BI's full query output.

A temporary local project was saved, reopened, reparsed from the same workbook,
and replayed: it again returned **573 × 14**, the same headers and rows as the
pre-save local preview, and the same footer. The workbook SHA-256 was unchanged.
This manual check exercises project serialization plus source reparse and local
step replay; it does not exercise the UI controller's full open/refresh path.
See [Iteration 50 test results](../.council/TEST_RESULTS_ITER50.md) for the
automated verification and remaining compatibility boundaries.

## Iteration 51 live partition metadata and raw worksheet source (2026-10-21)

A read-only ADOMD connection to the running Power BI Desktop 2.157.879.0 model resolved the source/navigation query that was unknown in Iteration 50. The live model has separate VAT 5% objects: raw query VAT 5% (622 rows after row 1 is promoted) and cleaned query Table 3 (VAT 5%) (573 rows × 14, including Grand Total). The captured raw source is `Excel.Workbook(File.Contents(...), null, true)`: the second argument (`useHeaders`) is null and the third (`delayTypes`) is true, followed by an explicit Promoted Headers step for worksheet row 1. The clean query uses `Excel.Workbook(..., null, false)`, then trims the worksheet and promotes its business-header row. Microsoft documents the argument order and recommends `Table.PromoteHeaders` for explicit header promotion in the [Excel.Workbook reference](https://learn.microsoft.com/en-ca/powerquery-m/excel-workbook).

The clean partition's captured M definition is recorded with the workbook path redacted in [the Iteration 51 evidence artifact](verification-artifacts/rea-powerbi-live-partitions-iter51.json). It starts at the worksheet's unpromoted data, named Column1…Column14, then applies the observed sparse-bottom predicate, sparse-top predicate, PromoteAllScalars=true, and explicit Changed Type for all 14 fields. This explains Iteration 50's boundary mismatch: local row-1 parsing hid the first worksheet row before M; Power BI's clean query retained it.

Live stage counts are 623 → 585 → 574 → 573. A DAX summary query on the current model returned 573 rows, 1,498,307.26 for Value including Grand Total, and 572 detail rows / 749,153.63 excluding Grand Total. No Power BI UI action or model/workbook write was performed.

Analytics Studio now has a persisted Excel raw_rows source option. It retains physical worksheet row numbers through the declared range even when blank trailing <row> XML tags are omitted, uses Column1…ColumnN names, and is selected by default for Transform. Load retains the previous automatic/manual header behavior. The actual local VAT workbook now replays at 623 → 585 → 574 → 573 and returns the same headers/footer and the same totals rounded to two decimals. The source workbook hash is unchanged. The local unrounded Decimal totals differ below one trillionth from the displayed Power BI values, so this iteration claims matching displayed totals, not bit-for-bit floating-point equivalence.

After review, declared-range bounds and trailing padding were restricted to raw Transform so oversized XLSX metadata cannot alter automatic Load or add phantom columns. Explicit-header imports continue to preserve physical blank gaps used by row-count operations, without importing an undeclared tail. Legacy `.xls` raw mode uses xlrd's BIFF row/column dimension metadata where exposed. The generated workbook regression now fills all 14 fields and the end-to-end path covers preview Transform → Close & Load → save/reopen/refresh.

Final verification passed **981 tests and 722 subtests**; the focused import/Transform selection passed **190 tests and 217 subtests**. The supplied workbook was replayed read-only after the final parser changes; its source hash remained unchanged. A new REA native-window capture on the main display was unavailable because the selected proxy bounds matched two accessibility candidates, so the live comparison relies on the earlier read-only ADOMD model evidence rather than a new screenshot.

This live evidence supersedes Iteration 50's hypothesis about an extra Navigation row. The current partition DMV identifies the no-header workbook source as the reason for the one-row bottom-trim difference. It is still not a Mashup runtime trace and applies only to this running Desktop model/version.

## Iteration 60 — Excel Load source identity (2026-10-21)

The retained live partition artifact shows that this Power BI model contains
two tables from the same workbook: `VAT 5%` with 622 rows after an explicit
row-1 promotion, and `Table 3 (VAT 5%)` with 573 cleaned rows × 14 columns.
The raw query's `Excel.Workbook(..., null, true)` does **not** mean
`UseHeaders=true`; its `useHeaders` argument is null and `delayTypes` is true,
then a separate `Promoted Headers` step uses worksheet row 1. This distinction
is grounded in the [Microsoft Excel.Workbook reference](https://learn.microsoft.com/en-ca/powerquery-m/excel-workbook)
and the captured source definition in [the Iteration 51 artifact](verification-artifacts/rea-powerbi-live-partitions-iter51.json).

Analytics Studio's fresh Excel import preview now selects row 1 as the Load
header, so the supplied workbook preview returns the observed 622-row `VAT 5%`
shape. Automatic header detection remains selectable and returns the separate
573-row business-header shape. The Transform raw-row choice is independent of
Load's header setting and is checked by default; selecting it reparses the
worksheet as 623 unpromoted rows. Reimporting a linked workbook starts with its
saved parser options, while parser-wide defaults and legacy migrations remain
unchanged.

Verification used the actual workbook read-only. Row-1 Load returned 622 × 14;
automatic detection returned 573 × 14; raw Transform input returned 623 × 14.
The workbook SHA-256 remained
`8f7e4656a03b487d4fbe504718aec372c5564d8fc80b5eca38769434ba003965` before
and after. The full suite passed **993 tests and 738 subtests**; the scoped
import suite passed **102 tests and 138 subtests**. This aligns a fresh Load
choice to this observed model table; it does not automatically reproduce the
separate Power Query cleanup, establish a universal Power BI connector default,
or resolve the user's exact DAX calculation. No Power BI query or project was
edited or saved.

### Iteration 60 implementation review follow-up

Review found that local Excel source identity compared worksheet and header row
but not `raw_rows`. Because both automatic-header and raw-row modes use
`header_row=None`, one could overwrite the other. Source matching now checks
raw-row mode before exact or legacy header matching. A regression creates both
sources, checks their IDs before and after project reopen, and verifies the
preview replacement callback resolves the automatic candidate and raw
Transform candidate to their respective sources. Critic and lifecycle review
approved the fix. This is local source-lifecycle evidence; it adds no new
Power BI runtime finding and does not close broader M/DAX or visual parity.

## Iteration 52 read-only window observation (2026-10-21)

After the user authorized use of the main display, REA attempted a read-only
accessibility/screenshot observation of Power BI Desktop PID 38836, window
16606. It failed with `capability_unavailable` / `ambiguous-window`: the
selected Parallels proxy bounds `(32, 874, 149, 171)` matched two accessibility
window candidates. The operation performed no clicks or key entry and did not
change the Power BI window. No new visual or runtime behavior evidence was
obtained; Iteration 51 ADOMD metadata and earlier selected-step UI captures
remain the available REA comparison sources.
# Iteration 52 — Main-display window observation (2026-10-21)

- The user authorized use of the main display. REA captured the already-open Power BI Desktop window (PID 38836, window 12568, title `Untitled - Power BI Desktop`) with screenshot-only mode. Evidence: `ev_626d3c5cff990fbae6ff826129909fba0f147ae000c055bf5e651cf2cb13c136`; screenshot 157×182 px.
- REA also captured the Power Query Editor window (PID 38836, window 16606, title `Untitled - Power Query Editor`) in screenshot-only mode. Evidence: `ev_8f2bfc8d7d71213337e5ea1e25e2fd9a3f9734d6585df4e9faaea3e2a9665607`.
- Both observations bind to Parallels `WinAppHelper` (Mach-O arm64, SHA-256 `8886a1e14b3f2294975757c49dfdd825e76c43365375d9c583bd12a1793cadcb`). They show the guest UI surface, not the Power BI Windows executable, process internals, or Mashup runtime.
- Accessibility capture for the Power BI Desktop window failed with `ambiguous-window`: selected proxy bounds `(16, 868, 157, 182)` mapped to two AX candidates `(49, 82, 1958, 1198)` and `(-7, 32, 2070, 1304)`. No UI actions were attempted.
- REA could not observe the local Analytics Studio Qt process (PID 33066, window 15771) after opening its Python 3.14 Mach-O target; the process did not expose a launch time required for stable identity validation. Local automated tests remain the verification source for that app.
- The proxy screenshots are too small to read labels or compare control behavior. This observation adds no feature-parity conclusion; the integrated Power Query header-filter → Apply → save/reopen → source-refresh lifecycle remains an open test gap.

## Iteration 53 — Main-display Power Query comparison (2026-10-21)

After the user authorized use of the main display, the already-running Power BI
Desktop guest was brought forward by its exact host process identity. REA then
captured readable screenshots for its Data view and Power Query Editor:

- Data view: `ev_a6ead99766effbebd9e30771f0a46320504eba6d043b4e35edeac3babf7c16df`.
- Power Query with `FilterNullAndWhitespace` selected: `ev_dbb9ae29e9cc5f78d22f7ec9be87804a74a1d06ee5233432c8610c31c4f0d24d`.
- Power Query after selecting the existing final `Changed Type` step: `ev_90678a1035357ea8cb02d8b708394adc9fa980f9259c05fedf0c3d1bcdd09eb0`.

The only Power BI UI change was selecting the existing `Changed Type` step to
show its preview. No M expression was edited, no query was applied, and the
project was not saved. The Data view capture has the separate `VAT 5%` table
selected and reports 622 rows. The Power Query capture shows `Table 3 (VAT 5%)`
with 573 rows and 14 columns, plus the formula bar and its seven applied steps.
The local Analytics Studio window showed a `Table 3 (VAT 5%)` preview with the
same 573 × 14 shape. This does not establish cell-by-cell equality or matching
model inventory: Data view and Power Query were showing different tables.

REA identified the target as the Parallels `WinAppHelper` host process (PID
38836, arm64 Mach-O, SHA-256
`8886a1e14b3f2294975757c49dfdd825e76c43365375d9c583bd12a1793cadcb`). The AX
tree exposed only each top-level window node. This is visual guest-UI evidence;
it does not inspect the Power BI Windows executable, its internal process, or
the Mashup runtime. Earlier Iteration 51 read-only ADOMD metadata remains the
backend evidence for that specific running model.

## Iteration 54 — Selected-step filter observation attempt (2026-10-21)

- REA observed the already-running Power Query Editor window in the Parallels
  guest (PID 38836, window 16606, title `Untitled - Power Query Editor`).
- Evidence: `ev_7809d508253fcd79ea16d5c7320c807b863c4ba398c5e93638b66759c61dbbf6`;
  screenshot SHA-256:
  `c5649ed7df59df7f22c9a043b92a58938f14824b909f11b838f9a340a66d0768`.
- REA returned one `AXWindow` node with no accessible child controls, so this
  capture cannot select a non-final step or author a header filter. No UI
  action was attempted and the user's Power BI query was not changed.
- Microsoft documents that selecting an Applied Step shows its result and
  that a new intermediate step is inserted after the selected step. This is
  documented workflow evidence, not a new REA runtime observation. The
  implementation and tests must avoid claiming direct Power BI behavioral
  acceptance from this capture.

## Iteration 55 — Active-window Power Query recheck (2026-10-21)

After the user authorized use of the main display, Power BI was brought forward
and REA captured the selected Power Query Editor window:

- Evidence: `ev_f91dd2d1ef1aeda820f347a9fbcb6e5156038dd793f8c3e8f56a3e2258dd54e7`.
- Selected query: `Table 3 (VAT 5%)`, 14 columns and 573 rows.
- Seven listed Applied Steps: Source, Navigation, FilterNullAndWhitespace,
  Removed Bottom Rows, Removed Top Rows, Promoted Headers, and Changed Type.
- Accessibility still returned only the AXWindow root, with zero child
  controls. The capture confirms the visible query state but not the behavior
  of its filter button.

Two non-mutating filter-menu click attempts (host coordinate automation and a
guest-side attempt) did not open the menu; one changed Stage Manager's active
group, after which the same Power BI query was restored. No query step was
applied and no project was saved. The live local Transform dialog visible
earlier in this pass showed the raw 623-row worksheet with no steps. A separate
local Table 3 preview screenshot at
`/tmp/analytics-studio-matched-preview.png` shows 14 columns × 573 rows and
the same first visible Date/Particulars rows as the Power BI screenshot at
`/tmp/powerbi-restored.png`. This is a shape and visible-row comparison, not
cell-by-cell parity or a same-state interaction test. No new backend/Mashup
evidence was obtained.

## Iteration 58 — `DIVIDE` alternate engine check (2026-10-21)

A read-only ADOMD connection queried the running Power BI Desktop
**2.157.879.0** model with scalar `EVALUATE ROW(...)` expressions. The results
were:

- `DIVIDE(1, 0, 5)` returned `5`.
- `DIVIDE(1, 0, BLANK())` returned blank; `ISBLANK(...)` returned `TRUE`.
- Arithmetic (`1 + 2`), `ABS(-1)`, and an aggregate expression as the third
  argument were rejected with Power BI's diagnostic that the alternate result
  on divide-by-zero must be a constant numeric value.
- `DIVIDE(1, 0, -1)` returned `-1`.

The queries were read-only and did not change the model or project. They
establish only these tested `DIVIDE` forms. They do not reproduce the user's
reported incorrect calculation, because its exact measure expression and
filter context are not known. Microsoft's [DIVIDE documentation](https://learn.microsoft.com/en-us/dax/divide-function-dax)
also specifies a constant alternate result.

## Iteration 59 — `DIVIDE` blank operands (2026-10-21)

Read-only scalar `EVALUATE ROW(...)` queries through ADOMD against the running
Power BI Desktop **2.157.879.0** engine returned:

- `DIVIDE(BLANK(), 2)` and `DIVIDE(BLANK(), 0, 9)` returned blank.
- `DIVIDE(1, BLANK())` returned blank; `DIVIDE(1, BLANK(), 9)` returned `9`.
- `DIVIDE(BLANK(), TRUE(), 9)` returned blank. This establishes the expression's
  result, not whether Power BI evaluates or skips the denominator.
- `DIVIDE(COALESCE(BLANK(), BLANK()), 0, 9)` and
  `DIVIDE(DIVIDE(1, 0), 0, 9)` returned blank.
- `DIVIDE(TRUE(), 2)` returned `0.5`; `DIVIDE(FALSE(), 2)` returned `0`.
- `DIVIDE(1, TRUE(), 9)` returned `1`; `DIVIDE(1, FALSE(), 9)` returned `9`.
- `ABS(BLANK())` returned blank; `COALESCE(ABS(BLANK()), 7)` returned `7`;
  `DIVIDE(ABS(BLANK()), 2)` returned blank.
- `COALESCE(BLANK() + 1, 7)` returned `1`;
  `DIVIDE(1, ABS(BLANK()), 9)` returned `9`.
- `DIVIDE(BLANK(), BLANK(), 9)` returned blank, while `DIVIDE(0, 0, 9)` returned
  `9`.

The ADOMD queries used the Parallels guest's current-user channel and did not
modify the model or project. REA's native UI capture was retried as a wait-only
observation, but the host still matched the selected Power BI window to two
accessibility windows and returned `ambiguous-window` before any interaction.
No UI action or project mutation occurred. These results justify only the
listed expressions; the user's exact incorrect formula and filter context
remain unknown.

## Iteration 61 — chart-axis `ALLSELECTED` comparison (2026-10-21)

The running Windows Power BI Desktop **2.157.879.0** model was queried through
read-only ADOMD against the cleaned `Table 3 (VAT 5%)` table. The grouped DAX
shape selected Dubai and Abu Dhabi, calculated each category's sum, calculated
the selected total with qualified `ALLSELECTED` on Emirates, and divided each
sum by that total:

```DAX
EVALUATE
SUMMARIZECOLUMNS(
    'Table 3 (VAT 5%)'[Emirates],
    TREATAS({"Dubai", "Abu Dhabi"}, 'Table 3 (VAT 5%)'[Emirates]),
    "Value", SUM('Table 3 (VAT 5%)'[Value]),
    "Selected Total",
        CALCULATE(
            SUM('Table 3 (VAT 5%)'[Value]),
            ALLSELECTED('Table 3 (VAT 5%)'[Emirates])
        ),
    "Share",
        DIVIDE(
            SUM('Table 3 (VAT 5%)'[Value]),
            CALCULATE(
                SUM('Table 3 (VAT 5%)'[Value]),
                ALLSELECTED('Table 3 (VAT 5%)'[Emirates])
            )
        )
)
```

Power BI returned Dubai **259,801.81 / 665,967.32 / 0.390111950238039** and
Abu Dhabi **406,165.51 / 665,967.32 / 0.609888049761961** for Value, Selected
Total, and Share. A second read-only query materialized those groups and
expressions in a `SUMMARIZECOLUMNS` variable, then applied `TOPN(1, __Core,
[V], DESC)`. It returned only Abu Dhabi while preserving selected total
**665,967.32** and share **0.609888049761961**. This confirms that the captured
axis selection must precede Top N trimming for this tested query shape.

Analytics Studio now carries a bounded axis-selection context for saved
measures on one non-stacked chart axis when the axis and measure share a model
table and the measure calls qualified `ALLSELECTED` on that exact axis column.
It preserves other column filters and relationship roots. Tests cover a
separate Month filter, a related-table filter root, a plain-SUM chart and Card
controls, save/reopen/source refresh, and a public `visualSeries` call after a
saved Top 1 filter. The public Top N regression selects North/East/South and
returns only East at **90/215**.

REA's current session was checked after the user authorized the main display.
Its native-macOS UI provider still reports `capture_native_ui_scenario`
unavailable because the selected proxy bounds `(-259, 224, 176, 177)` match two
accessibility windows; `observe_native_ui` is unavailable because its
audio/video capture stream fails to start. No click or key entry was attempted.
The ADOMD comparison is live engine evidence, not a fresh REA UI observation.
This is evidence for one qualified axis-column query pattern, not a diagnosis
of the user's unknown DAX expression or a claim of general DAX/visual parity.

After the user authorized the main display, a passive window inventory
identified the local Analytics Studio window (PID 33066, window 15771) and the
Parallels Power BI helper windows. A window-targeted `screencapture` captured
the local Data view without activation; `prlctl capture 'Windows 11'` captured
the guest without clicking or changing focus. The local app shows `VAT 5%` at
**573 rows × 14 columns**. Power BI Power Query shows `Table 3 (VAT 5%)` at
**573 rows × 14 columns** with the Changed Type step selected. The first visible
record's date, particulars, and emirate match in the two captures. This is a
shape and visible-record check only, not a full row-by-row comparison. The
screenshots are `/tmp/analytics-studio-main-window-iter61.png` and
`/tmp/powerbi-iter61.png`. The Power BI project remained unchanged and unsaved.

## Iteration 62 — Excel text decoding and live table comparison (2026-10-21)

The local Power Query replay and the running Power BI Desktop **2.157.879.0**
model were compared using the same VAT workbook source and the unique
`Voucher No` key. The source workbook's SHA-256 was
`8f7e4656a03b487d4fbe504718aec372c5564d8fc80b5eca38769434ba003965`. The
transformed local table and loaded `Table 3 (VAT 5%)` both contain 573 rows ×
14 columns, with the same ordered headers and no unmatched keys. The comparison
used a read-only ADOMD query; the Power BI project was not changed or saved.

Inspection found Excel OOXML `_xHHHH_` escapes in shared, inline, and cached
text. The importer now decodes them once and preserves escaped literal tokens.
The local parser had returned the encoded text literally. Microsoft's
[ST_Xstring specification](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/d34ae755-c53f-4a44-a363-c6dd3ee018a4)
documents the carriage-return escape and `_x005f_` handling used to preserve a
literal escape-like token.

After this fix, `Value`, `Gross Total`, `Sales`, `VAT-5%`, and `Discount` match
the loaded model within 1e-6. Strict text comparison still finds 8 differing
`Particulars` cells, 3 `Address` cells, and 1 `Emirates` cell. The affected
`Particulars` pairs compare equal after whitespace trimming; the other four
pairs compare equal after case-folding. These are diagnostic equivalences;
Analytics Studio preserves the source text. Microsoft's
[Tabular collation notes](https://learn.microsoft.com/en-us/analysis-services/tabular-models/string-storage-and-collation-in-tabular-models?view=sql-analysis-services-2025)
describe canonical spellings for collation-equivalent text, which is
consistent with the case-only observations but does not establish every
cell's transformation path.

The local Power Query preview reports 32 `DataFormat.Error` values in `TRN`,
while the loaded Power BI model returns blanks for those positions. Keep the
query errors intact through preview; any confirmed conversion to model blanks
belongs at a distinct model-load boundary. Do not normalize workbook values at
import based only on the equivalence diagnostic. This is a partial comparison,
not strict full-table equality or a claim of general Power BI parity.



## Iteration 64 — DAX differential harness and scalar math (2026-10-21)

The running Power BI Desktop **2.157.879.0** engine was queried read-only over ADOMD, using `Microsoft.PowerBI.AdomdClient.dll` from the Power BI package folder, from the Parallels guest. `tools/dax_oracle_diff.py` evaluates a battery of constant and aggregate DAX expressions in that engine and in the local evaluator and classifies each pair as `match`, `gap-reject` (local rejects, Power BI answers), or `DIFF`. The harness creates a six-row `Facts` calculated table (blanks, a zero, a negative) in the unsaved in-memory model and deletes it at the end of every run; it never saves the Power BI project. A Power BI-side `ROW("v", <expr>)` query needs at least one table in the model.

Baseline battery (93 expressions, `tools/dax_battery.json`): 47 matches, 43 `gap-reject`, and no mismatch among supported functions once the harness passed the app's typed column context. Two apparent differences were harness mistakes and are recorded here so they are not re-opened: the model represents a blank cell as `None` and `""` is distinct empty text, and column types must be supplied as the app supplies them. Confirmed Power BI results include `CALCULATE(COUNTROWS(Facts), Facts[Sales]=BLANK())` counting both blank and `0` (2 of 6 rows) and `DISTINCTCOUNTNOBLANK` skipping blank.

The 43 gaps are unsupported functions and forms (for example `SWITCH`, `IFERROR`, `CONCATENATE`, `LEN`, `ISBLANK`, `FORMAT`, `VALUES`, `SELECTEDVALUE`, `VAR/RETURN`, string comparison, the `^` operator, boolean results, `BLANK()` arithmetic, `1/0` as Infinity). This iteration implemented the scalar math slice (`INT`, `TRUNC`, `SIGN`, `SQRT`, `EXP`, `LN`, `MOD`, `POWER`); on 49 edge expressions, 47 match (including inputs both engines reject) and 2 are the documented gaps in `DAX_COMPATIBILITY_CONTRACT.md`. An independent review of the first implementation found four defects (28-digit limit in `TRUNC`/`MOD`, no double-range guard, negative zero, literal `BLANK()` rejected), all fixed with regression tests. Re-running the 93-expression baseline afterward gave 58 matches, 35 unsupported, 0 mismatches.

The user's own data was loaded into the Power Query Editor during the session but not applied to the model, so no table-level comparison was possible this iteration. REA UI capture was not used; the guest screen was captured once with `prlctl capture` and showed an unrelated application, so nothing from it was used.


## Iteration 65 — blank arithmetic and conditional functions (2026-10-21)

`tools/dax_oracle_diff.py` (iteration 64) was run against the live engine for 264 expressions covering blank arithmetic, `IF`/`ISBLANK`/`IFERROR`/`SWITCH`, `CEILING`/`FLOOR`, `MEDIAN`/`PRODUCT`/`COUNTBLANK` and row iterators: 230 match, 34 are refused locally, none differ. Observed behaviours are listed in `DAX_COMPATIBILITY_CONTRACT.md` (iteration 65). One mismatch found on the way: `IFERROR(1/0>1, 2)` is `True` in Power BI (the Infinity feeds the comparison), so division by zero reaching a comparison, `ISBLANK` or `SWITCH` is refused instead of guessed.

## Iteration 66 — the user's workbook through Power BI's own importer (2026-10-21)

**Method (no screen, no guest capture).** `tools/table_oracle_diff.py` creates a scratch table in the unsaved Power BI model through TMSL (`createOrReplace` with an M partition `Excel.Workbook(File.Contents("\\\\Mac\\Home\\Downloads\\DSI.xlsx"), null, false)` → `Table.Skip(…, 5)` → `Table.PromoteHeaders` → `Table.TransformColumnTypes`), refreshes it, dumps every cell through `EVALUATE`, runs a measure battery with `ROW("v", expr)`, and drops the table. The file is only read; the Power BI project is never saved. The user confirmed `Downloads/DSI.xlsx` (Tally "Direct Purchase Invoice List", banner in rows 1–5, header at row 6, 371 data rows including a grand-total row and a "Printed by" footer) as the test data.

**Findings.**
- Power BI's headless import of the workbook returned the same 371 rows as the local importer with `header_row=6`.
- **Excel doubles:** the workbook stores `66.150000000000006`; Power Query reads the double 66.15. The local importer kept the 17 digits. Fixed (`file_import._excel_cell_value`).
- **Trailing spaces and case in the loaded model:** 15 text cells in the workbook end in a space (`PREPAID CARDS `, `EXTRA PAID 10/AED FOR `). Power Query keeps them (`Text.Length` on the M side counted them), the model does not: `SUMX(DSI, LEN(DSI[Party Name]))` equals the sum of right-trimmed lengths, `DISTINCTCOUNT(DSI[Remarks])` is 160 against 163, and `CALCULATE(COUNTROWS(DSI), DSI[Party Name]="PREPAID CARDS ")` is blank. Probes on M tables (`#table` literals, `Csv.Document`) fixed the exact rule: U+0000–U+0020 are trimmed at the end (tab, LF, CR, VT, FF, controls too), U+0085, U+00A0, U+2000-series, U+3000, U+007F are not; whitespace-only becomes `""`; ASCII letters are case-insensitive with the first-seen spelling stored (`EXACT` confirms all variants read as the first); non-ASCII letters are distinct; calculated tables (`DATATABLE`) keep trailing spaces; `Csv.Document` yields `""` for empty fields (`DISTINCTCOUNT` 2, `DISTINCTCOUNTNOBLANK` 2, `COUNTBLANK` 3 on `North,/West, /East,0`).
- The Power Query candidate (preview, M operations) keeps raw text; the model candidate gets the load rules in `_model_candidate_with_format_errors_as_blank` — the model-load boundary the iteration 62 note asked for.

**Result after the fixes.** All 371 × 10 cells identical; 108 workbook measure expressions: 106 match, 2 refused (`COUNTROWS(FILTER(DSI, DSI[Net Amount] > 10000))` = 8 and `SUMX(FILTER(DSI, DSI[VAT Amt] > 0), DSI[VAT Amt])` = 58,679.82 — iterators over a `FILTER` table are not supported locally), 0 differ. Because the file is a real report, the grand-total row (`PI#` = 369, Net 617,330.15) is counted by `SUM` in Power BI and locally alike; removing it is a Power Query step the user would add.
