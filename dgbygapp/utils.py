import re
from typing import Dict, List, Tuple, Union, Optional
import math
import concurrent.futures
from contextlib import contextmanager
from dGbyG.api import Compound, Reaction

# 定义固定条件
default_T = 298.15
default_I = 0.25
default_pMg = 14.0

@contextmanager
def timeout_context(seconds):
    """线程安全的超时上下文管理器"""
    # 简化版本：对于dGbyG计算，我们暂时移除超时控制
    # 如果需要超时控制，建议在上层使用concurrent.futures.ThreadPoolExecutor
    try:
        yield
    except Exception as e:
        raise

def get_reaction_conditions() -> Dict[str, Dict[str, float]]:
    """
    获取预定义的反应条件
    
    Returns:
        Dict[str, Dict[str, float]]: 反应条件字典
    """
    return {
        'd': {'pH': 7.00, 'e_potential': 0, 'T': default_T, 'I': default_I, 'pMg': default_pMg},
        'c': {'pH': 7.20, 'e_potential': 0, 'T': default_T, 'I': default_I, 'pMg': default_pMg},
        'e': {'pH': 7.40, 'e_potential': 30 * 1e-3, 'T': default_T, 'I': default_I, 'pMg': default_pMg},
        'n': {'pH': 7.20, 'e_potential': 0, 'T': default_T, 'I': default_I, 'pMg': default_pMg},
        'r': {'pH': 7.20, 'e_potential': 0, 'T': default_T, 'I': default_I, 'pMg': default_pMg},
        'g': {'pH': 6.35, 'e_potential': 0, 'T': default_T, 'I': default_I, 'pMg': default_pMg},
        'l': {'pH': 5.50, 'e_potential': 19 * 1e-3, 'T': default_T, 'I': default_I, 'pMg': default_pMg},
        'm': {'pH': 8.00, 'e_potential': -155 * 1e-3, 'T': default_T, 'I': default_I, 'pMg': default_pMg},
        'i': {'pH': 8.00, 'e_potential': -155 * 1e-3, 'T': default_T, 'I': default_I, 'pMg': default_pMg},
        'x': {'pH': 7.00, 'e_potential': 12 * 1e-3, 'T': default_T, 'I': default_I, 'pMg': default_pMg}
    }

def parse_cid(cid: str) -> Tuple[str, str]:
    """
    解析化合物ID，格式为 "cid_type:cid"

    Args:
        cid: 化合物ID，格式如 "pubchem:123" 或 "bigg:h2o_c"

    Returns:
        Tuple[str, str]: (化合物名称, 标识符类型)
    """
    if ':' in cid:
        cid_type, compound_name = cid.split(':', 1)
        return compound_name.strip(), cid_type.strip()
    else:
        # 如果没有冒号，抛出错误，要求明确指定类型
        raise ValueError(f'Invalid cid: {cid}. Please use the format of "cid_type:cid".')

def parse_compound(compound: str) -> Tuple[float, str]:
    match = re.match(r'^(\d+(?:\.\d+)?)\s+(.+)$', compound)
    if match:
        num = match.group(1)
        name = match.group(2).strip()
        num = float(num) if num else 1.0
        return num, name
    else:
        return 1.0, compound

def parse_equation(equation: str) -> Tuple[List[str], List[float]]:
    """
    解析反应方程式，提取化合物和系数 
    Args:
        equation: 反应方程式，如 "2 H2O = H2 + O2"
        
    Returns:
        Tuple[List[str], List[float]]: (化合物列表, 系数列表)
    """
    lhs, rhs = equation.split(' = ', 1)
    substrates = [c.strip() for c in lhs.split(' + ')]
    products = [c.strip() for c in rhs.split(' + ')]

    compound_names = []
    stoichiometries = []

    for c in substrates:
        coeff, name = parse_compound(c)
        compound_names.append(name)
        stoichiometries.append(-coeff)

    for c in products:
        coeff, name = parse_compound(c)
        compound_names.append(name)
        stoichiometries.append(coeff)

    return compound_names, stoichiometries

def create_reaction_with_conditions(
    equation: str,
    identifier: str = 'compound',
    condition_type: str = 'd',
    custom_condition: Optional[Union[Dict[str, float], Dict[int, Dict[str, float]]]] = None
) -> 'Reaction':
    """
    创建反应对象并设置条件
    """

    if condition_type == 'custom':
        # 判定是否为“全局自定义条件”
        is_global = (
            isinstance(custom_condition, dict)
            and all(k in custom_condition for k in ('pH', 'I', 'pMg', 'e_potential'))
            and not any(isinstance(k, int) for k in custom_condition.keys())
        )

        if is_global:
            # === 全局自定义条件 ===
            if identifier == 'mixed':
                reaction = Reaction(equation)  # 不传 cids_type，让内部自行解析
            else:
                reaction = Reaction(equation, cids_type=identifier)

            for compound in reaction.reaction:
                compound.condition.update(custom_condition)  # 应用全局条件

        else:
            # === 逐化合物自定义条件 ===
            compound_names, stoichiometries = parse_equation(equation)
            compound_objs = []

            for index, compound_name in enumerate(compound_names):
                if identifier == 'mixed':
                    # 自动解析前缀/类型
                    compound_onlyname, cid_type = parse_cid(compound_name)
                    compound_obj = Compound(compound_onlyname, cid_type=cid_type)
                else:
                    compound_obj = Compound(compound_name, cid_type=identifier)

                if isinstance(custom_condition, dict) and (index in custom_condition or str(index) in custom_condition):
                    # 支持数字键和字符串键
                    condition_data = custom_condition.get(index) or custom_condition.get(str(index))
                    if condition_data:
                        compound_obj.condition.update(condition_data)

                compound_objs.append(compound_obj)

            # for 循环结束后再组装字典并构造 Reaction
            equation_dict = dict(zip(compound_objs, stoichiometries))
            reaction = Reaction(equation_dict)

    else:
        # === 预定义条件 ===
        conditions = get_reaction_conditions()
        chosen_condition = conditions.get(condition_type)
        if not chosen_condition:
            raise ValueError('Invalid reaction condition')

        if identifier == 'mixed':
            reaction = Reaction(equation)
        else:
            reaction = Reaction(equation, cids_type=identifier)

        for compound in reaction.reaction:
            compound.condition.update(chosen_condition)

    return reaction


def calculate_dg(
    reaction_str: str,
    identifier: str = 'compound',
    condition_type: str = 'd',
    custom_condition: Optional[Union[Dict[str, float], Dict[int, Dict[str, float]]]] = None
) -> Dict[str, Union[float, str]]:
    """
    计算反应的ΔG值

    Args:
        reaction_str: 反应方程式
        identifier: 化合物标识符类型
        condition_type: 反应条件类型
        custom_condition: 自定义条件

    Returns:
        Dict[str, Union[float, str]]: 计算结果或错误信息
    """
    try:
        with timeout_context(60):
            reaction = create_reaction_with_conditions(reaction_str, identifier, condition_type, custom_condition)
            dG_prime, dG_std_dev = reaction.transformed_standard_dGr_prime

            # 格式化数值，保留2位小数
            dG_prime_formatted = round(float(dG_prime), 2)
            dG_std_dev_formatted = round(float(dG_std_dev), 2)

            result = {
                'dG_prime': dG_prime_formatted,
                'dG_std_dev': dG_std_dev_formatted
            }
            return result

    except TimeoutError as e:
        error_msg = f"Calculation timed out: {str(e)}"
        return {'error': error_msg}
    except Exception as e:
        error_msg = f"Calculation failed: {str(e)}"
        return {'error': error_msg}


def nan_to_none(obj):
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: nan_to_none(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [nan_to_none(x) for x in obj]
    return obj