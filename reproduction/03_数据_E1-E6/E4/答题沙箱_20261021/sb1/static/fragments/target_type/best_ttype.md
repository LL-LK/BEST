# target_type/best_ttype — astro-best 星表面切片
- CatalogType 成员以 `src/models/__init__.py::CatalogType` 为唯一真源（14 个）:
  STD / PS1 / CALIB_STRIPE82 / CALIB_GAIA / CALIB_GAIA_18 / CALIB_JPLUS /
  CALIB_SMSS / CALIB_LANDOLT / CALIB_USS / CALIB_SPLUS / SCR_GALAH / SCR_LAMOST /
  XPSP / DR3XPCORR;
- STD 是 Standard Stars **导航分组、不是可查询表**（`/std/q` 软 404）；其线上成员是
  SCR_GALAH / SCR_LAMOST / XPSP —— 按名字查表别选 STD;
- 注意带 `CALIB_` 前缀才是成员名（JPLUS/SMSS/LANDOLT/USS/SPLUS 都不是成员名）;
  `CALIB_GAIA`(="gaia_dr3") 与 `CALIB_GAIA_18`(="gaia_dr3_18") 是两个独立成员, 不是别名;
- 匹配半径默认 gaia_dr3=5.0 arcsec, ps1=3.0 arcsec;
- CSV 落盘走 csv_safety (公式注入防御)。
