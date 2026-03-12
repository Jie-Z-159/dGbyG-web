import os
from model_analyzer import get_available_models, search_by_model_structured, get_available_models_cached
from reaction_analyzer import (
    search_by_reaction_structured, 
    search_metabolites_by_query_structured,
    find_genes_by_query
)

def search_database_structured(query, data_dir="result", model_filter=None):
    """
    结构化版本的统一搜索函数：返回结构化数据而不是print输出

    Args:
        query: 搜索关键词
        data_dir: 数据目录（用于模型搜索）
        model_filter: 模型过滤列表

    Returns:
        dict: 包含模型、反应、代谢物搜索结果的字典
    """
    import time
    start_time = time.time()
    print(f"🔍 [DEBUG] Starting search for query: '{query}'")

    # 获取当前文件的目录路径
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # 构建绝对路径
    data_dir = os.path.join(current_dir, data_dir)

    results = {
        'query': query,
        'models': [],
        'reactions': [],
        'metabolites': [],
        'genes': [],
        'summary': {
            'total_models_found': 0,
            'total_reactions_found': 0,
            'total_metabolites_found': 0,
            'total_genes_found': 0,
            'has_results': False
        }
    }

    try:
        # 1. Model search - 使用优化的缓存版本
        print(f"🏥 [DEBUG] Step 1: Starting model search...")
        step_start = time.time()
        available_models = get_available_models_cached()
        model_matches = [model for model in available_models if query.lower() in model.lower()]
        print(f"🏥 [DEBUG] Step 1: Found {len(model_matches)} model matches in {time.time()-step_start:.2f}s")

        if model_matches:
            # 为每个匹配的模型获取详细信息
            model_details = []
            for i, model_id in enumerate(model_matches):
                print(f"🏥 [DEBUG] Processing model {i+1}/{len(model_matches)}: {model_id}")
                model_info = search_by_model_structured(model_id, data_dir)
                if model_info:
                    model_details.append(model_info)

            results['models'] = model_details
            results['summary']['total_models_found'] = len(model_details)
            results['summary']['has_results'] = True

        # 2. Reaction search - 使用优化的搜索函数
        print(f"⚛️ [DEBUG] Step 2: Starting reaction search...")
        step_start = time.time()
        reaction_results = search_by_reaction_structured(query, model_filter=model_filter)
        print(f"⚛️ [DEBUG] Step 2: Found {len(reaction_results) if reaction_results else 0} reactions in {time.time()-step_start:.2f}s")
        if reaction_results:
            results['reactions'] = reaction_results
            results['summary']['total_reactions_found'] = len(reaction_results)
            results['summary']['has_results'] = True

        # 3. Metabolite search - 使用合并后的优化函数
        print(f"🧪 [DEBUG] Step 3: Starting metabolite search...")
        step_start = time.time()
        metabolite_results = search_metabolites_by_query_structured(query, model_filter=model_filter)
        print(f"🧪 [DEBUG] Step 3: Found {len(metabolite_results) if metabolite_results else 0} metabolites in {time.time()-step_start:.2f}s")
        if metabolite_results:
            results['metabolites'] = metabolite_results
            results['summary']['total_metabolites_found'] = len(metabolite_results)
            results['summary']['has_results'] = True

        # 4. Gene search - 新增基因搜索功能
        print(f"🧬 [DEBUG] Step 4: Starting gene search...")
        step_start = time.time()
        try:
            gene_results = find_genes_by_query(query, model_filter=model_filter)
            print(f"🧬 [DEBUG] Step 4: Found {len(gene_results) if gene_results else 0} genes in {time.time()-step_start:.2f}s")
            if gene_results:
                results['genes'] = gene_results
                results['summary']['total_genes_found'] = len(gene_results)
                results['summary']['has_results'] = True
        except Exception as e:
            print(f"❌ [DEBUG] Gene search failed: {e}")
            import traceback
            traceback.print_exc()
            # 基因搜索失败不影响其他搜索功能

        total_time = time.time() - start_time
        print(f"Search completed: {total_time:.1f}s")  # 简化输出格式
        return results

    except Exception as e:
        print(f"❌ [DEBUG] Search failed with error: {e}")
        import traceback
        traceback.print_exc()
        raise 