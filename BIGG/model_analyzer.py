import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import json
from functools import lru_cache

def get_available_models(data_dir="result"):
    """Get list of available models"""
    models = []
    if os.path.exists(data_dir):
        for file in os.listdir(data_dir):
            if file.endswith('_standard_dGr_dGbyG.csv'):
                model_id = file.replace('_standard_dGr_dGbyG.csv', '')
                models.append(model_id)
    return sorted(models)

@lru_cache(maxsize=8)
def get_available_models_cached(_: str = '') -> list:
    """获取可用模型列表（缓存版）"""
    # 尝试从reaction_analyzer获取，如果失败则使用传统方法
    try:
        from reaction_analyzer import _ensure_loaded, _MODELS
        _ensure_loaded()
        return list(_MODELS)
    except:
        # 回退到传统方法
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(current_dir, "result")
        return get_available_models(data_dir)

def analyze_dg_distribution(dg_data):
    """Analyze ΔG distribution statistics"""
    valid_dg = dg_data['standard_dGr_prime(kJ/mol)'].dropna()
    
    # Basic statistics
    stats = {
        'total_reactions': len(dg_data),
        'valid_dg_reactions': len(valid_dg),
        'mean_dg': valid_dg.mean(),
        'std_dg': valid_dg.std(),
        'min_dg': valid_dg.min(),
        'max_dg': valid_dg.max(),
        'median_dg': valid_dg.median()
    }
    
    # Reaction classification statistics
    stats.update({
        'exergonic_reactions': (valid_dg < 0).sum(),
        'endergonic_reactions': (valid_dg > 0).sum(),
        'near_equilibrium_reactions': (abs(valid_dg) < 5).sum(),
        'highly_exergonic': (valid_dg < -50).sum(),
        'highly_endergonic': (valid_dg > 50).sum()
    })
    
    return stats

def load_model_statistics(model_id, model_stats_dir="model_stats"):
    """Load model statistics"""
    stats_file = os.path.join(model_stats_dir, f"{model_id}_statistics.json")
    if os.path.exists(stats_file):
        try:
            with open(stats_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Cannot read model statistics file: {e}")
    return None

def load_model_conditions(model_id, cond_file="model_conditions_new.csv"):
    """Load model conditions information"""
    if os.path.exists(cond_file):
        try:
            cond_df = pd.read_csv(cond_file)
            row = cond_df[cond_df['BiGG ID'] == model_id]
            if not row.empty:
                return json.loads(row.iloc[0]['Conditions_new'])
        except Exception as e:
            print(f"Warning: Cannot read conditions file: {e}")
    return None

def display_model_info(model_id, model_stats, conditions):
    """Display model information"""
    print(f"\n=== Model Information: {model_id} ===")
    
    # Display statistics
    if model_stats:
        print("\n📊 Model Statistics:")
        print(f"  Total reactions: {model_stats.get('total_reactions', 'N/A')}")
        print(f"  Boundary reactions: {model_stats.get('boundary_reactions', 'N/A')}")
        print(f"  Covered reactions: {model_stats.get('covered_reactions', 'N/A')}")
        print(f"  Unstructured reactions: {model_stats.get('unstructured_reactions', 'N/A')}")
        print(f"  Unbalanced reactions: {model_stats.get('unbalanced_reactions', 'N/A')}")
        print(f"  Reversible/Irreversible: {model_stats.get('covered_reversible_vs_irreversible', 'N/A')}")
        print(f"  Single/Multi-compartment: {model_stats.get('covered_single_vs_multi_compartment', 'N/A')}")
    else:
        print("\n❌ Model statistics not found")
    
    # Display conditions
    if conditions:
        print("\n🌡️ Compartment Conditions:")
        for comp, cond in conditions.items():
            print(f"  {comp}: {cond}")
    else:
        print("\n❌ Conditions information not found")

def plot_dg_distribution(distribution, valid_dg, model_id):
    """Plot ΔG distribution"""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle(f'ΔG Distribution for {model_id}', fontsize=15, fontweight='bold')

    # Histogram + KDE
    sns.histplot(valid_dg, bins=40, kde=True, color='steelblue', ax=axes[0], 
                edgecolor='black', alpha=0.7)
    axes[0].axvline(0, color='red', linestyle='--', label='ΔG = 0')
    axes[0].set_title('ΔG Histogram & KDE')
    axes[0].set_xlabel('ΔG (kJ/mol)')
    axes[0].set_ylabel('Count')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # ΔG statistics
    axes[1].axis('off')
    stats_text = f"""
    Model: {model_id}

    ΔG Data Statistics:
    - Reactions with ΔG data: {distribution['valid_dg_reactions']}
    - Mean ΔG: {distribution['mean_dg']:.2f} kJ/mol
    - Std ΔG: {distribution['std_dg']:.2f} kJ/mol
    - Min ΔG: {distribution['min_dg']:.2f} kJ/mol
    - Max ΔG: {distribution['max_dg']:.2f} kJ/mol
    - Median ΔG: {distribution['median_dg']:.2f} kJ/mol

    ΔG Reaction Types:
    - Exergonic (ΔG < 0): {distribution['exergonic_reactions']}
    - Endergonic (ΔG > 0): {distribution['endergonic_reactions']}
    - Near equilibrium (|ΔG| < 5): {distribution['near_equilibrium_reactions']}
    - Highly exergonic (ΔG < -50): {distribution['highly_exergonic']}
    - Highly endergonic (ΔG > 50): {distribution['highly_endergonic']}
    """
    axes[1].text(0, 1, stats_text, fontsize=11, verticalalignment='top', fontfamily='monospace')

    plt.tight_layout()
    plt.show()

def search_by_model(model_id, data_dir="result", model_stats_dir="model_stats", cond_file="model_conditions_new.csv"):
    """Search and analyze specified model"""
    # Check if model exists
    available_models = get_available_models(data_dir)
    if model_id not in available_models:
        print(f"❌ Error: Model {model_id} not found")
        print(f"Available models:")
        for i, model in enumerate(available_models, 1):
            print(f"  {i:2d}. {model}")
        return None
    
    # Load ΔG data
    csv_file = os.path.join(data_dir, f"{model_id}_standard_dGr_dGbyG.csv")
    try:
        dg_data = pd.read_csv(csv_file)
        if dg_data.columns[0] != "reaction_id":
            dg_data.columns = ["reaction_id", "standard_dGr_prime(kJ/mol)", "SD(kJ/mol)"]
    except Exception as e:
        print(f"❌ Error: Cannot load data file: {e}")
        return None
    
    # Load model information
    model_stats = load_model_statistics(model_id, model_stats_dir)
    conditions = load_model_conditions(model_id, cond_file)
    
    # Display model information
    display_model_info(model_id, model_stats, conditions)
    
    # Analyze ΔG distribution and plot
    distribution = analyze_dg_distribution(dg_data)
    valid_dg = dg_data['standard_dGr_prime(kJ/mol)'].dropna()
    plot_dg_distribution(distribution, valid_dg, model_id)

def search_by_model_structured(model_id, data_dir="result", model_stats_dir="model_stats", cond_file="model_conditions_new.csv"):
    """
    结构化版本的模型搜索函数：返回结构化数据而不是print输出和绘图
    
    Args:
        model_id: 模型ID
        data_dir: 数据目录
        model_stats_dir: 模型统计目录
        cond_file: 条件文件路径
        
    Returns:
        dict: 包含模型信息的字典，如果模型不存在则返回None
    """
    # 获取当前文件的目录路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 构建绝对路径
    data_dir = os.path.join(current_dir, data_dir)
    model_stats_dir = os.path.join(current_dir, model_stats_dir)
    cond_file = os.path.join(current_dir, cond_file)
    
    # Check if model exists
    available_models = get_available_models(data_dir)
    if model_id not in available_models:
        return None
    
    # Load ΔG data
    csv_file = os.path.join(data_dir, f"{model_id}_standard_dGr_dGbyG.csv")
    try:
        dg_data = pd.read_csv(csv_file)
        # Select only needed columns and rename
        dg_data = dg_data[['reaction_id_bigg', 'standard_dGr_prime(kJ/mol)', 'SD(kJ/mol)']]
        dg_data.columns = ["reaction_id", "standard_dGr_prime(kJ/mol)", "SD(kJ/mol)"]
    except Exception as e:
        return None
    
    # Load model information
    model_stats = load_model_statistics(model_id, model_stats_dir)
    conditions = load_model_conditions(model_id, cond_file)
    
    # Analyze ΔG distribution
    distribution = analyze_dg_distribution(dg_data)
    valid_dg = dg_data['standard_dGr_prime(kJ/mol)'].dropna()
    
    # Generate charts
    chart_filename = None
    dg_chart_filename = None
    
    if model_stats:
        try:
            chart_filename = generate_simple_chart(model_id, model_stats)
        except Exception as e:
            print(f"Warning: Could not generate reaction classification chart for {model_id}: {e}")
    
    if len(valid_dg) > 0:
        try:
            dg_chart_filename = generate_dg_distribution_chart(model_id, distribution, valid_dg)
            print(f"Generated ΔG distribution chart for {model_id}: {'Success' if dg_chart_filename else 'Failed'}")
        except Exception as e:
            print(f"Warning: Could not generate ΔG distribution chart for {model_id}: {e}")
            dg_chart_filename = None
    else:
        print(f"No valid ΔG data for {model_id}")
        dg_chart_filename = None
    
    # 构建结构化结果
    result = {
        'model_id': model_id,
        'model_stats': model_stats,
        'conditions': conditions,
        'dg_distribution': distribution,
        'chart_filename': chart_filename,
        'dg_chart_filename': dg_chart_filename,
        'dg_data': {
            'total_reactions': len(dg_data),
            'valid_dg_reactions': len(valid_dg),
            'dg_values': valid_dg.tolist() if len(valid_dg) > 0 else [],
            'reaction_ids': dg_data['reaction_id'].tolist(),
            'dg_values_with_ids': dg_data[['reaction_id', 'standard_dGr_prime(kJ/mol)', 'SD(kJ/mol)']].to_dict('records')
        }
    }
    
    return result

def generate_simple_chart(model_id, model_stats):
    """
    生成Sunburst图并返回HTML div
    
    Args:
        model_id: 模型ID
        model_stats: 模型统计信息
        
    Returns:
        str: HTML div字符串，如果失败则返回None
    """
    try:
        import plotly.graph_objects as go
        from plotly.offline import plot
        
        # 提取数据
        total = model_stats.get('total_reactions', 0)
        boundary = model_stats.get('boundary_reactions', 0)
        covered = model_stats.get('covered_reactions', 0)
        unbalanced = model_stats.get('unbalanced_reactions', 0)
        unstructured = model_stats.get('unstructured_reactions', 0)
        reversible = model_stats.get('covered_reversible', 0)
        irreversible = model_stats.get('covered_irreversible', 0)
        
        # 检查是否有数据
        if total == 0:
            return None
        
        # 构建Sunburst图数据
        labels = [
            "Total Reactions",
            "Boundary", "Unstructured", "Unbalanced", "Covered",
            "Reversible", "Irreversible"
        ]

        parents = [
            "",  # Total has no parent
            "Total Reactions", "Total Reactions", "Total Reactions", "Total Reactions",
            "Covered", "Covered"
        ]

        values = [
            total,  # Total
            boundary, unstructured, unbalanced, covered,
            reversible, irreversible
        ]

        fig = go.Figure(go.Sunburst(
            labels=labels,
            parents=parents,
            values=values,
            branchvalues="total"
        ))

        fig.update_layout(
            margin=dict(t=120, l=0, r=0, b=0),
            title={
                'text': f"Reaction Classification - {model_id}<br><sub>Total: {total} | Boundary: {boundary} | Unstructured: {unstructured}<br>Unbalanced: {unbalanced} | Covered: {covered} (Rev: {reversible}, Irrev: {irreversible})</sub>",
                'x': 0.5,
                'xanchor': 'center',
                'font': {'size': 16}
            },
            height=500,
            showlegend=False
        )

        plot_div = plot(fig, output_type='div', include_plotlyjs=True)
        
        return plot_div
        
    except Exception as e:
        print(f"Error generating chart: {e}")
        return None

def generate_dg_distribution_chart(model_id, distribution, valid_dg):
    """
    生成ΔG分布图并返回HTML div
    
    Args:
        model_id: 模型ID
        distribution: ΔG分布统计信息
        valid_dg: 有效的ΔG数据
        
    Returns:
        str: HTML div字符串，如果失败则返回None
    """
    try:
        import plotly.graph_objects as go
        from plotly.offline import plot
        
        # 创建直方图
        fig = go.Figure()
        
        fig.add_trace(go.Histogram(
            x=valid_dg,
            nbinsx=40,
            name='ΔG',
            marker=dict(color='steelblue', line=dict(color='black', width=1)),
            opacity=0.7
        ))

        # 红线：ΔG = 0
        fig.add_shape(type="line",
                     x0=0, x1=0, y0=0, y1=1,
                     xref='x', yref='paper',
                     line=dict(color="red", width=2, dash="dash"))

        fig.update_layout(
            title={
                'text': f"Δ<sub><i>r</i></sub>G° Distribution - {model_id}<br><sub>Mean: {distribution['mean_dg']:.2f} kJ/mol | Std: {distribution['std_dg']:.2f} kJ/mol | Range: {distribution['min_dg']:.2f} to {distribution['max_dg']:.2f} kJ/mol</sub>",
                'x': 0.5,
                'xanchor': 'center',
                'font': {'size': 16}
            },
            xaxis_title="Δ<sub><i>r</i></sub>G° (kJ/mol)",
            yaxis_title="Count",
            height=500,
            margin=dict(t=60, l=20, r=20, b=20),
            showlegend=False
        )

        plot_div = plot(fig, output_type='div', include_plotlyjs=True)
        
        return plot_div
        
    except Exception as e:
        print(f"Error generating ΔG distribution chart: {e}")
        return None