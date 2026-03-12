import os
import re
import json
import threading
from typing import List, Dict, Optional

import pandas as pd
from collections import defaultdict

# ===== 全局数据对象 =====
_DF_PART: Optional[pd.DataFrame] = None     # 明细参与表（每行：某模型-某反应-某代谢物）
_DF_RXN:  Optional[pd.DataFrame] = None     # 反应级索引表（每行：一个 reaction_id）
_DF_MET:  Optional[pd.DataFrame] = None     # 代谢物级索引表（每行：一个 (met_bigg_id, met_universal_bigg_id)）
_DF_GENE: Optional[pd.DataFrame] = None     # 基因表（每行：某模型-某反应-某基因）
_MODELS:  Optional[List[str]] = None        # 模型集合
_LOCK = threading.RLock()

# ===== 基因搜索：规范化与索引 =====
_GENE_IDX_BY_ID: Optional[Dict[str, List[int]]] = None
_GENE_IDX_BY_NAME: Optional[Dict[str, List[int]]] = None
_GENE_READY = False

# ===== 缓存路径配置 =====
CACHE_DIR = '.cache'
CACHE_FILES = {
    'participation': 'bigg_participation.feather',
    'reactions': 'bigg_reactions.feather',
    'metabolites': 'bigg_metabolites.feather',
    'genes': 'bigg_genes.feather',
    'gene_indexes': 'gene_indexes.json',
    'metadata': 'metadata.json'
}

# ===== 基础工具 =====
def _load_metabolite_image(metabolite_id: str) -> str:
    """加载代谢物图像数据（base64编码）"""
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        image_file = os.path.join(current_dir, 'image_biggid', f'{metabolite_id}.txt')
        if os.path.exists(image_file):
            with open(image_file, 'r') as f:
                return f.read().strip()
    except Exception as e:
        print(f"Warning: Could not load image for {metabolite_id}: {e}")
    return ""

def _load_from_cache() -> bool:
    """从缓存文件加载数据，如果成功返回True"""
    global _DF_PART, _DF_RXN, _DF_MET, _DF_GENE, _MODELS, _GENE_IDX_BY_ID, _GENE_IDX_BY_NAME, _GENE_READY

    current_dir = os.path.dirname(os.path.abspath(__file__))
    cache_dir = os.path.join(current_dir, CACHE_DIR)

    try:
        # 检查所有缓存文件是否存在
        for cache_file in CACHE_FILES.values():
            cache_path = os.path.join(cache_dir, cache_file)
            if not os.path.exists(cache_path):
                print(f"Cache file missing: {cache_path}")
                return False

        print("Loading BIGG data...")  # 简化加载提示

        # 加载Feather文件
        _DF_PART = pd.read_feather(os.path.join(cache_dir, CACHE_FILES['participation']))
        _DF_RXN = pd.read_feather(os.path.join(cache_dir, CACHE_FILES['reactions']))
        _DF_MET = pd.read_feather(os.path.join(cache_dir, CACHE_FILES['metabolites']))
        _DF_GENE = pd.read_feather(os.path.join(cache_dir, CACHE_FILES['genes']))

        # 加载JSON文件
        with open(os.path.join(cache_dir, CACHE_FILES['gene_indexes']), 'r', encoding='utf-8') as f:
            gene_indexes = json.load(f)
            _GENE_IDX_BY_ID = gene_indexes['by_id']
            _GENE_IDX_BY_NAME = gene_indexes['by_name']
            _GENE_READY = True

        with open(os.path.join(cache_dir, CACHE_FILES['metadata']), 'r', encoding='utf-8') as f:
            metadata = json.load(f)
            _MODELS = metadata['models']

        print("BIGG data loaded")  # 简化加载提示
        return True

    except Exception as e:
        print(f"❌ Failed to load from cache: {e}")
        return False

def _norm(s: str) -> str:
    """规范化字符串：转小写，去除空格、连字符、点、下划线、斜杠"""
    s = (s or "").strip().lower()
    return re.sub(r'[\s\-\._/]+', '', s)

def _mk_search_blob(*parts: str) -> str:
    return "\n".join([p for p in parts if isinstance(p, str)]).lower()

def _tokenize_query(q: str) -> str:
    """清理并返回单个搜索词，移除分号等特殊字符"""
    q = (q or '').strip().lower()
    # 移除分号和其他可能的分隔符，只保留第一个词组
    q = re.split(r'[;,|]+', q)[0].strip() if q else ""
    return q if q else ""

def _calculate_relevance_score(search_blob: str, query: str, id_field: str, name_field: str = "") -> int:
    """简单的相关度评分：ID精确匹配 > 名称精确匹配 > 包含匹配"""
    if not query:
        return 0

    search_blob = search_blob.lower()
    id_lower = id_field.lower()
    name_lower = name_field.lower() if name_field else ""
    query_lower = query.lower()

    # ID精确匹配，最高分
    if query_lower == id_lower:
        return 100
    # 名称精确匹配，高分
    elif query_lower == name_lower:
        return 80
    # ID包含匹配，中等分
    elif query_lower in id_lower:
        return 60
    # 名称包含匹配，中等分
    elif name_lower and query_lower in name_lower:
        return 40
    # 其他字段包含匹配，基础分
    elif query_lower in search_blob:
        return 20
    else:
        return 0

def _ensure_gene_indexes():
    """构建基因搜索索引（规范化列 + 反向索引字典），幂等"""
    global _GENE_IDX_BY_ID, _GENE_IDX_BY_NAME, _GENE_READY, _DF_GENE
    _ensure_loaded()
    if _DF_GENE is None or _DF_GENE.empty:
        _GENE_READY = False
        return
    with _LOCK:
        if _GENE_READY:
            return
        if '__norm_id' not in _DF_GENE.columns:
            _DF_GENE['__norm_id'] = _DF_GENE['gene_id'].astype(str).map(_norm)
        if '__norm_name' not in _DF_GENE.columns:
            _DF_GENE['__norm_name'] = _DF_GENE['gene_name'].astype(str).map(_norm)
        by_id, by_name = defaultdict(list), defaultdict(list)
        for i, (nid, nname) in enumerate(zip(_DF_GENE['__norm_id'], _DF_GENE['__norm_name'])):
            if nid: by_id[nid].append(i)
            if nname: by_name[nname].append(i)
        _GENE_IDX_BY_ID, _GENE_IDX_BY_NAME = dict(by_id), dict(by_name)
        _GENE_READY = True

def _ensure_loaded():
    """
    确保数据已加载，仅使用缓存
    """
    global _DF_PART, _DF_RXN, _DF_MET, _DF_GENE, _MODELS
    with _LOCK:
        if all(x is not None for x in (_DF_PART, _DF_RXN, _DF_MET, _DF_GENE, _MODELS)):
            return

        # 尝试从缓存加载
        if _load_from_cache():
            return

        # 如果缓存加载失败，这通常是系统问题
        raise RuntimeError(
            "Failed to load BIGG data from cache. This may indicate a file system issue or corrupted cache files."
        )

# ===== 公开 API =====
def load_reaction_data():
    """兼容原接口的数据加载函数（预热）"""
    _ensure_loaded()

def get_reaction_data():
    """兼容原接口的数据获取函数"""
    _ensure_loaded()
    return _DF_PART

# -------- 反应搜索 ----------
def find_reactions_by_query(
    query: str,
    model_filter: Optional[List[str]] = None,
    max_results: int = 200
) -> List[Dict]:
    """优化的反应搜索，支持模型过滤，按相关度排序"""
    _ensure_loaded()
    clean_query = _tokenize_query(query)
    if not clean_query:
        return []

    df = _DF_RXN
    # 简单的包含搜索
    mask = df['search_blob'].str.contains(clean_query, case=False, regex=False, na=False)
    sub = df[mask]

    if model_filter:
        mf = set(model_filter)
        sub = sub[sub['model_list'].apply(lambda L: bool(mf.intersection(L)))]

    results = []
    for _, r in sub.iterrows():
        model_list = r.get('model_list', [])
        if model_filter:
            model_list = [m for m in model_list if m in model_filter]

        # 计算相关度得分
        relevance_score = _calculate_relevance_score(
            r.get('search_blob', ''),
            clean_query,
            r.get('reaction_id', ''),
            r.get('reaction_name', '')
        )

        results.append({
            'id': r['reaction_id'],
            'name': r.get('reaction_name', ''),
            'equation': r.get('equation', ''),
            'model_list': model_list,
            'relevance_score': relevance_score
        })

    # 按相关度排序（分数高的在前）
    results.sort(key=lambda x: x['relevance_score'], reverse=True)

    if max_results and max_results > 0:
        results = results[:max_results]

    # 移除relevance_score字段，保持API兼容性
    for result in results:
        result.pop('relevance_score', None)

    return results

def get_reaction_dg_data(
    reaction_id: str,
    model_list: Optional[List[str]] = None
) -> List[Dict]:
    """获取反应的热力学数据（从参与表直接汇总）"""
    _ensure_loaded()
    df = _DF_PART
    sub = df[df['reaction_id'] == reaction_id][[
        'model', 'reaction_id', 'equation', 'standard_dGr_prime(kJ/mol)', 'SD(kJ/mol)'
    ]].drop_duplicates()

    if model_list:
        sub = sub[sub['model'].isin(model_list)]

    out = []
    for _, row in sub.iterrows():
        dgr = row['standard_dGr_prime(kJ/mol)']
        sd  = row['SD(kJ/mol)']
        equation = row['equation']
        out.append({
            "model_id": row['model'],
            "reaction_id": row['reaction_id'],
            "equation": equation if equation and not pd.isna(equation) else "",
            "standard_dGr_prime": None if dgr=='' or pd.isna(dgr) else round(float(dgr), 2),
            "SD": None if sd=='' or pd.isna(sd) else round(float(sd), 2),
        })
    return out

def search_by_reaction_structured(
    reaction_query: str,
    model_filter: Optional[List[str]] = None,
    max_results: int = 100
) -> List[Dict]:
    """结构化反应搜索：基本信息 + 延迟加载 ΔG"""
    matches = find_reactions_by_query(reaction_query, model_filter=model_filter, max_results=max_results)
    if not matches:
        return []
    return [{
        'reaction_info': {
            'id': m['id'],
            'name': m['name'],
            'equation': m['equation'],
            'model_list': m['model_list'],
        },
        'models_data': []  # 需要时再调用 get_reaction_dg_data 加载
    } for m in matches]

def search_reactions_with_thermo(
    reaction_query: str,
    model_filter: Optional[List[str]] = None,
    max_results: int = 50
) -> List[Dict]:
    """搜索反应并包含热力学数据"""
    structured_results = search_by_reaction_structured(
        reaction_query, model_filter=model_filter, max_results=max_results
    )
    if not structured_results:
        return []
    for result in structured_results:
        reaction_id = result['reaction_info']['id']
        result['models_data'] = get_reaction_dg_data(reaction_id, model_list=model_filter)
    return structured_results

# -------- 代谢物搜索 ----------
def find_metabolites_by_query(
    query: str,
    model_filter: Optional[List[str]] = None,
    max_results: int = 200
) -> List[Dict]:
    """优化的代谢物搜索（name / bigg / universal / formula），按相关度排序"""
    _ensure_loaded()
    clean_query = _tokenize_query(query)
    if not clean_query:
        return []

    df = _DF_MET
    # 简单的包含搜索
    mask = df['search_blob'].str.contains(clean_query, case=False, regex=False, na=False)
    sub = df[mask]

    if model_filter:
        mf = set(model_filter)
        sub = sub[sub['model_list'].apply(lambda L: bool(mf.intersection(L)))]

    out = []
    for _, r in sub.iterrows():
        model_list = r.get('model_list', [])
        if model_filter:
            model_list = [m for m in model_list if m in model_filter]

        # 计算相关度得分
        relevance_score = _calculate_relevance_score(
            r.get('search_blob', ''),
            clean_query,
            r.get('met_bigg_id', ''),
            r.get('met_name', '')
        )

        out.append({
            'id': r['met_bigg_id'],
            'name': r.get('met_name', ''),
            'universal_id': r.get('met_universal_bigg_id', ''),
            'formula': r.get('formula', ''),
            'charge': r.get('charge', ''),
            'compartments': r.get('compartments', []),
            'model_list': model_list,
            'relevance_score': relevance_score
        })

    # 按相关度排序（分数高的在前）
    out.sort(key=lambda x: x['relevance_score'], reverse=True)

    if max_results and max_results > 0:
        out = out[:max_results]

    # 移除relevance_score字段，保持API兼容性
    for result in out:
        result.pop('relevance_score', None)

    return out

def find_reactions_for_metabolite(
    metabolite_id: str,
    model_filter: Optional[List[str]] = None,
    max_results: int = 200
) -> List[Dict]:
    """查找包含指定代谢物（bigg 或 universal）的反应 + 带化学计量信息"""
    _ensure_loaded()
    mid = (metabolite_id or '').strip()
    if not mid:
        return []

    df = _DF_PART
    sub = df[(df['met_bigg_id'] == mid) | (df['met_universal_bigg_id'] == mid)]

    if model_filter:
        sub = sub[sub['model'].isin(model_filter)]

    results = []
    for reaction_id, group in sub.groupby('reaction_id'):
        if max_results and len(results) >= max_results:
            break
        first_row = group.iloc[0]
        stoich = group[['met_bigg_id', 'met_universal_bigg_id', 'met_name', 'stoich_coeff', 'compartment']].drop_duplicates()
        model_list = sorted([m for m in group['model'].unique().tolist() if m.strip()])
        if model_filter:
            model_list = [m for m in model_list if m in model_filter]
        results.append({
            'reaction_id': reaction_id,
            'name': first_row.get('reaction_name', ''),
            'equation': first_row.get('equation', ''),
            'model_list': model_list,
            'stoichiometry': stoich.to_dict('records')
        })
    return results

def search_metabolites_by_query_structured(
    query: str,
    model_filter: Optional[List[str]] = None,
    max_results: int = 100,
    include_reactions: bool = True
) -> List[Dict]:
    """代谢物结构化搜索：代谢物信息 +（可选）其参与的反应"""
    mets = find_metabolites_by_query(query, model_filter=model_filter, max_results=max_results)
    if not mets:
        return []

    results = []
    for m in mets:
        img_data = _load_metabolite_image(m['universal_id'])  # 使用 universal_id
        item = {
            'metabolite_info': {
                'id': m['id'],
                'name': m['name'],
                'universal_id': m['universal_id'],
                'formula': m['formula'],
                'charge': m['charge'],
                'compartments': m['compartments'],
                'model_list': m['model_list'],
                'img_data': img_data,
            },
            'reactions': []
        }
        if include_reactions:
            item['reactions'] = find_reactions_for_metabolite(m['id'], model_filter=model_filter, max_results=50)
        results.append(item)
    return results

# -------- 基因搜索 ----------
def find_genes_by_query(
    query: str,
    model_filter: Optional[List[str]] = None,
    max_results: int = 100
) -> List[Dict]:
    """
    基因搜索功能，聚合基因数据并返回结构化结果
    """
    import time
    start_time = time.time()
    print(f"  🧬 [GENE DEBUG] Starting gene search for: '{query}'")

    _ensure_loaded()
    if _DF_GENE is None or _DF_GENE.empty:
        print(f"  🧬 [GENE DEBUG] No gene data available")
        return []

    clean_query = _tokenize_query(query)
    if not clean_query:
        print(f"  🧬 [GENE DEBUG] No valid query")
        return []

    df = _DF_GENE
    print(f"  🧬 [GENE DEBUG] Total gene records: {len(df)}")

    # 过滤有效的基因数据
    step_start = time.time()
    valid_genes = df[
        (df['gene_id'].notna()) &
        (df['gene_id'] != '') &
        (df['gene_id'] != 'nan') &
        (df['gene_name'].notna()) &
        (df['gene_name'] != '') &
        (df['gene_name'] != 'nan')
    ]
    print(f"  🧬 [GENE DEBUG] Valid genes after filtering: {len(valid_genes)} (took {time.time()-step_start:.2f}s)")

    if valid_genes.empty:
        return []

    # 在gene_id和gene_name中搜索
    step_start = time.time()
    gene_mask = (
        valid_genes['gene_id'].astype(str).str.contains(clean_query, case=False, na=False) |
        valid_genes['gene_name'].astype(str).str.contains(clean_query, case=False, na=False)
    )
    matched_genes = valid_genes[gene_mask]
    print(f"  🧬 [GENE DEBUG] Genes matching query: {len(matched_genes)} (took {time.time()-step_start:.2f}s)")

    if matched_genes.empty:
        return []

    if model_filter:
        step_start = time.time()
        matched_genes = matched_genes[matched_genes['model'].isin(model_filter)]
        print(f"  🧬 [GENE DEBUG] After model filter: {len(matched_genes)} (took {time.time()-step_start:.2f}s)")

    # 按(gene_id, gene_name)聚合
    step_start = time.time()
    print(f"  🧬 [GENE DEBUG] Starting groupby aggregation...")

    def aggregate_gene_data(group):
        """聚合基因数据，按反应ID聚合但保留模型特异性"""
        reaction_groups = group.groupby('reaction_id')
        reactions = []

        for reaction_id, reaction_group in reaction_groups:
            if not reaction_id or str(reaction_id).strip() == '' or str(reaction_id) == 'nan':
                continue

            # 反应名称（第一个非空）
            reaction_name = next(
                (str(row['reaction_name']).strip()
                 for _, row in reaction_group.iterrows()
                 if str(row['reaction_name']).strip() and str(row['reaction_name']) != 'nan'),
                ''
            )

            # 收集该反应在所有模型中的GPR信息
            gpr_to_models = {}  # GPR规则 -> 模型列表
            for _, row in reaction_group.iterrows():
                model = str(row['model']).strip()
                gpr = str(row['gpr']).strip()
                if model and model != 'nan':
                    if gpr and gpr != 'nan':
                        gpr_to_models.setdefault(gpr, []).append(model)

            # 去重后的GPR信息
            gpr_info = []
            for gpr, models in gpr_to_models.items():
                gpr_info.append({
                    'gpr': gpr,
                    'models': sorted(set(models))
                })

            reactions.append({
                'id': reaction_id,
                'name': reaction_name,
                'gpr_info': gpr_info
            })

        return {
            'gene_id': group.iloc[0]['gene_id'],
            'gene_name': group.iloc[0]['gene_name'],
            'models': sorted(set([str(x).strip() for x in group['model'] if str(x).strip() and str(x) != 'nan'])),
            'reactions': reactions
        }

    # 按基因聚合
    aggregated_results = []
    gene_groups = matched_genes.groupby(['gene_id', 'gene_name'])
    print(f"  🧬 [GENE DEBUG] Created {len(gene_groups)} gene groups (took {time.time()-step_start:.2f}s)")

    step_start = time.time()
    group_count = 0
    for (gene_id, gene_name), group in gene_groups:
        group_count += 1
        if group_count % 10 == 0:  # 每10个group输出一次进度
            print(f"  🧬 [GENE DEBUG] Processing group {group_count}/{len(gene_groups)}: {gene_id}")

        gene_data = aggregate_gene_data(group)

        # 应用模型过滤到聚合结果
        if model_filter:
            model_set = set(model_filter)
            # 过滤模型列表
            gene_data['models'] = [m for m in gene_data['models'] if m in model_set]
            if not gene_data['models']:
                continue

            # 过滤反应中的GPR信息
            filtered_reactions = []
            for rxn in gene_data['reactions']:
                filtered_gpr_info = []
                for gpr_item in rxn['gpr_info']:
                    filtered_models = [m for m in gpr_item['models'] if m in model_set]
                    if filtered_models:
                        filtered_gpr_info.append({
                            'gpr': gpr_item['gpr'],
                            'models': filtered_models
                        })
                if filtered_gpr_info:
                    filtered_reactions.append({
                        'id': rxn['id'],
                        'name': rxn['name'],
                        'gpr_info': filtered_gpr_info
                    })
            gene_data['reactions'] = filtered_reactions

        aggregated_results.append({
            'id': gene_data['gene_id'],
            'name': gene_data['gene_name'],
            'reactions': gene_data['reactions'],
            'model_list': gene_data['models'],
            'reaction_count': len(gene_data['reactions']),
            'model_count': len(gene_data['models'])
        })

    print(f"  🧬 [GENE DEBUG] Aggregation completed: {len(aggregated_results)} results (took {time.time()-step_start:.2f}s)")

    # 计算相关度并排序
    step_start = time.time()
    for result in aggregated_results:
        # 为基因计算相关度得分
        search_blob = f"{result['id']} {result['name']}".lower()
        relevance_score = _calculate_relevance_score(
            search_blob,
            clean_query,
            result['id'],
            result['name']
        )
        result['relevance_score'] = relevance_score

    # 按相关度排序，然后按反应数排序
    aggregated_results.sort(key=lambda x: (-x['relevance_score'], -x['reaction_count'], x['id']))
    print(f"  🧬 [GENE DEBUG] Sorting by relevance completed (took {time.time()-step_start:.2f}s)")

    # 移除相关度得分字段，保持API兼容性
    for result in aggregated_results:
        result.pop('relevance_score', None)

    if max_results and len(aggregated_results) > max_results:
        aggregated_results = aggregated_results[:max_results]
        print(f"  🧬 [GENE DEBUG] Limited to {max_results} results")

    total_time = time.time() - start_time
    print(f"  🧬 [GENE DEBUG] Gene search completed in {total_time:.2f}s")
    return aggregated_results

# ===== 维护/热重载 =====
def reload_data():
    """热重载数据，无需重启应用"""
    global _DF_PART, _DF_RXN, _DF_MET, _DF_GENE, _MODELS, _GENE_READY
    with _LOCK:
        _DF_PART = None
        _DF_RXN  = None
        _DF_MET  = None
        _DF_GENE = None
        _MODELS  = None
        _GENE_READY = False
    _ensure_loaded()
    print("Data reloaded successfully!")

def fully_warm_up():
    """完整预热，加载所有数据"""
    _ensure_loaded()
    _ensure_gene_indexes()
    from BIGG.model_analyzer import get_available_models_cached
    get_available_models_cached()