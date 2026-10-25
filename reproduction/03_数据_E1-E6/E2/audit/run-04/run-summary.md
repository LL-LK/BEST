# E2 查询结果与金标准一致性 跑批报告

- case 数: 21 (pass 7)
- 缺金标准: 无
- 缺快照: 无
- metascore (反证夹具): 1.00 (必须 1.00)
- 判定: FAIL

| case | 加权分 | 阻断项 |
|------|--------|--------|
| batch_proximity | 0.9500 | m4_structure:structure_mismatch |
| boundary_maxrows | 0.6000 | m1_rows:row_set_mismatch, m2_fields:field_mismatch, m4_structure:structure_mismatch |
| boundary_page_exact | 0.6000 | m1_rows:row_set_mismatch, m2_fields:field_mismatch, m4_structure:structure_mismatch |
| boundary_pole_dec | 0.4444 | m1_rows:row_set_mismatch, m2_fields:field_mismatch, m4_structure:structure_mismatch |
| boundary_radius0 | 1.0000 | — |
| boundary_wrap_ra | 0.6500 | m1_rows:row_set_mismatch, m2_fields:field_mismatch, m4_structure:structure_mismatch |
| cone_60as | 0.6000 | m1_rows:row_set_mismatch, m2_fields:field_mismatch, m4_structure:structure_mismatch |
| dense_field | 0.3889 | m1_rows:row_set_mismatch, m2_fields:field_mismatch, m4_structure:structure_mismatch |
| empty_field | 1.0000 | — |
| huge_batch_1000 | 0.5500 | m1_rows:row_set_mismatch, m2_fields:field_mismatch, m4_structure:structure_mismatch |
| huge_over_cap | 0.3889 | m1_rows:row_set_mismatch, m2_fields:field_mismatch, m4_structure:structure_mismatch |
| large_60000_rows | 0.3889 | m1_rows:row_set_mismatch, m2_fields:field_mismatch, m4_structure:structure_mismatch |
| missing_arg_catalog | 1.0000 | — |
| missing_arg_coords | 1.0000 | — |
| missing_arg_radius | 1.0000 | — |
| missing_cell | 0.6500 | m1_rows:row_set_mismatch, m2_fields:field_mismatch, m4_structure:structure_mismatch |
| missing_column | 1.0000 | — |
| multi_filter_mag_snr | 0.6000 | m1_rows:row_set_mismatch, m2_fields:field_mismatch, m4_structure:structure_mismatch |
| null_zero_twins | 0.4444 | m1_rows:row_set_mismatch, m2_fields:field_mismatch, m4_structure:structure_mismatch |
| single_exact | 0.4444 | m1_rows:row_set_mismatch, m2_fields:field_mismatch, m4_structure:structure_mismatch |
| soft404_page | 1.0000 | — |


- protocol: `E2-FROZEN-v2-2026-10-11`
- run_id: `e2-v2-0e794a338807456bb66c4b31791674c5`
- repeats: 0/63
- complete: False
- elapsed: 1.75s
- preregistration SHA-256: `9dc3881f30a1239a1db705c3d79144e6fac282ece9a6d605b1036df61c6c83b6`
