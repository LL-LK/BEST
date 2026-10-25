# 工具面 (真值, 从 src/ai_tools.py 的 ToolBox 抽)

- resolve_name(name)
- list_catalogs()
- describe_catalog(catalog)
- cone_search(ra, dec, radius_arcsec, catalog, columns, sort, order, nearest_only, max_rows)
- crossmatch_batch(coords, catalog, radius_arcsec, nearest_only, columns, max_rows)
- count(sqlid)
- fetch_page(sqlid, page, page_size, catalog, max_rows)

## 两处工具面边界 (易被误当成熟路)
- `resolve_name` 只解析**天体名** (CDS Sesame, 形如 "M31"), 不接受数字 `source_id`;
- `count`/`fetch_page` 只消费 `sqlid`, 而**没有工具能按条件生成 sqlid**。

## 数据面 (ps1 的 30 个列名; 排序列与列投影只能取这些)

- ps1_class_star, ps1_dec, ps1_dust, ps1_ebv, ps1_gflags, ps1_gpsf, ps1_gpsf_corr, ps1_gpsf_err, ps1_iflags, ps1_ipsf, ps1_ipsf_corr, ps1_ipsf_err, ps1_max_d, ps1_parallax, ps1_parallax_err, ps1_ra, ps1_rflags, ps1_rpsf, ps1_rpsf_corr, ps1_rpsf_err, ps1_ruwe, ps1_sigma, ps1_source_id, ps1_yflags, ps1_ypsf, ps1_ypsf_err, ps1_zflags, ps1_zpsf, ps1_zpsf_corr, ps1_zpsf_err

数据里**有**: 测光星等与误差、视差、径向速度(标量列)、teff/logg(标量列)、变星标志位
数据里**没有**: 光谱产品(一维谱)、图像/像素、历元序列本身、预报/外推
