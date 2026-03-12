from flask import render_template, request, jsonify, send_file, current_app, send_from_directory
from functools import wraps
from dgbygapp.forms import ReactionForm, UnifiedSearchForm, ContactForm
from dgbygapp.utils import calculate_dg, parse_compound, get_reaction_conditions, nan_to_none, parse_equation
import os
import tempfile
import sys
import time
from collections import defaultdict, deque
from datetime import datetime
from flask_mail import Message
from dgbygapp import mail

# 添加BIGG目录到Python路径
bigg_path = os.path.join(os.path.dirname(__file__), '..', 'BIGG')
if bigg_path not in sys.path:
    sys.path.append(bigg_path)

from unified_search_structured import search_database_structured  # type: ignore

# 简单的内存限流存储
class RateLimiter:
    def __init__(self):
        self.requests = defaultdict(deque)  # IP -> deque of timestamps

    def is_allowed(self, ip, limit, window_seconds):
        """检查IP是否允许请求"""
        now = time.time()
        # 清理过期的请求记录
        while self.requests[ip] and self.requests[ip][0] < now - window_seconds:
            self.requests[ip].popleft()

        # 检查是否超过限制
        if len(self.requests[ip]) >= limit:
            return False

        # 记录新请求
        self.requests[ip].append(now)
        return True

    def get_reset_time(self, ip, window_seconds):
        """获取限制重置时间"""
        if not self.requests[ip]:
            return 0
        return int(self.requests[ip][0] + window_seconds)

rate_limiter = RateLimiter()

def rate_limit(limit_per_hour=500):
    """限流装饰器 - 设置比较宽松的默认限制"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 获取客户端IP
            ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'unknown'))
            if ',' in ip:  # 处理多个代理的情况
                ip = ip.split(',')[0].strip()

            window_seconds = 3600  # 1小时

            if not rate_limiter.is_allowed(ip, limit_per_hour, window_seconds):
                reset_time = rate_limiter.get_reset_time(ip, window_seconds)
                return jsonify({
                    'error': 'Rate limit exceeded',
                    'limit': limit_per_hour,
                    'window': '1 hour',
                    'reset_time': reset_time
                }), 429

            return f(*args, **kwargs)
        return decorated_function
    return decorator

def handle_errors(f):
    """错误处理装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            print(f"ERROR in {f.__name__}: {str(e)}")  # 添加这行便于调试
            return jsonify({'error': str(e)}), 500
    return decorated_function

def validate_required_params(*required_params):
    """参数验证装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            for param in required_params:
                if not request.form.get(param):
                    return jsonify({'error': f'Missing required parameter: {param}'}), 400
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def init_routes(app):
    @app.before_request
    def log_requests():
        # 只记录非静态文件的重要请求
        if not request.path.startswith('/static/') and not request.path.startswith('/favicon'):
            app.logger.info(f"{request.method} {request.path} from {request.remote_addr}")

    @app.route('/robots.txt')
    def robots_txt():
        """Serve robots.txt for SEO"""
        return send_from_directory(app.root_path, 'robots.txt')

    @app.route('/sitemap.xml')
    def sitemap_xml():
        """Serve sitemap.xml for SEO"""
        return send_from_directory(app.root_path, 'sitemap.xml')

    @app.route('/')
    def home():
        return render_template('home.html')

    @app.route('/contact', methods=['GET', 'POST'])
    def contact():
        form = ContactForm()
        success = False
        error_message = None
        notification_message = None
        notification_level = 'info'

        if form.validate_on_submit():
            messages_file = os.path.join(current_app.config['BASE_DIR'], 'messages.txt')
            timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
            content_lines = [
                '-' * 70,
                f"Timestamp: {timestamp}",
                f"Name: {form.name.data}",
                f"Email: {form.email.data}",
                "Message:",
                form.message.data.strip(),
                ''
            ]
            try:
                os.makedirs(os.path.dirname(messages_file), exist_ok=True)
                with open(messages_file, 'a', encoding='utf-8') as fp:
                    fp.write('\n'.join(content_lines) + '\n')
                success = True
                # Attempt to send notification email
                recipient = current_app.config.get('MAIL_RECIPIENT')
                sender = current_app.config.get('MAIL_DEFAULT_SENDER') or current_app.config.get('MAIL_USERNAME')
                if recipient and current_app.config.get('MAIL_USERNAME') and current_app.config.get('MAIL_PASSWORD'):
                    subject = f"[dGbyG] New contact message from {form.name.data}"
                    body = (
                        f"A new message was submitted on {timestamp}.\n\n"
                        f"Name: {form.name.data}\n"
                        f"Email: {form.email.data}\n\n"
                        f"Message:\n{form.message.data.strip()}\n"
                    )
                    try:
                        msg = Message(
                            subject=subject,
                            sender=sender or form.email.data,
                            recipients=[recipient],
                            body=body,
                            reply_to=form.email.data if form.email.data else None
                        )
                        mail.send(msg)
                        notification_message = "Email notification sent successfully."
                        notification_level = 'success'
                    except Exception as exc:
                        current_app.logger.exception("Failed to send contact email")
                        notification_message = f"Message saved but email notification failed: {exc}"
                        notification_level = 'warning'
                else:
                    notification_message = "Message saved locally. Email notification is not configured."
                    notification_level = 'info'
                form = ContactForm()  # reset form after save/send attempts
            except Exception as exc:
                current_app.logger.exception("Failed to store contact message")
                error_message = f"Failed to save message: {exc}"

        return render_template('contact.html', form=form, success=success, error_message=error_message, notification_message=notification_message, notification_level=notification_level)

    @app.route('/gem-dg', methods=['GET', 'POST'])
    @rate_limit(limit_per_hour=300)  # GEM搜索：每小时300次
    def gem_dg():
        if request.method == 'GET':
            # GET请求返回网页界面
            form = UnifiedSearchForm()
            # 动态填充模型选择
            try:
                from BIGG.model_analyzer import get_available_models_cached  # type: ignore
                available_models = get_available_models_cached()
                form.model_filter.choices = [('', 'All Models')] + [(model, model) for model in available_models]
            except Exception as e:
                print(f"Warning: Could not load models for filter: {e}")
                form.model_filter.choices = [('', 'All Models')]
            return render_template('bigg.html', form=form, search_results=None, error=None)

        # POST请求处理
        if request.is_json:
            # JSON API请求
            try:
                data = request.get_json()
                if not data:
                    return jsonify({'error': 'JSON data required'}), 400

                query = data.get('query', '').strip()
                if not query:
                    return jsonify({'error': 'Query parameter is required'}), 400

                model_filter = data.get('model_filter')

                # 调用统一搜索功能
                model_filter_list = [model_filter] if model_filter else None
                search_results = search_database_structured(query, model_filter=model_filter_list)

                # 转换搜索结果为JSON格式
                result = {
                    'query': search_results['query'],
                    'summary': {
                        'total_models_found': search_results['summary']['total_models_found'],
                        'total_reactions_found': search_results['summary']['total_reactions_found'],
                        'total_metabolites_found': search_results['summary']['total_metabolites_found'],
                        'total_genes_found': search_results['summary']['total_genes_found']
                    },
                    'models': [],
                    'reactions': [],
                    'metabolites': [],
                    'genes': []
                }

                # 处理模型结果
                if search_results.get('models'):
                    for model in search_results['models']:
                        model_data = {
                            'model_id': model['model_id'],
                            'model_stats': model['model_stats'] if 'model_stats' in model else None,
                            'conditions': {}
                        }
                        if model.get('conditions'):
                            for comp, cond in model['conditions'].items():
                                model_data['conditions'][comp] = {
                                    'pH': cond['pH'],
                                    'T': cond['T'],
                                    'I': cond['I'],
                                    'pMg': cond['pMg'],
                                    'e_potential': cond['e_potential']
                                }
                        result['models'].append(model_data)

                # 处理反应结果
                if search_results.get('reactions'):
                    for reaction in search_results['reactions']:
                        reaction_data = {
                            'id': reaction['reaction_info']['id'],
                            'name': reaction['reaction_info']['name'],
                            'equation': reaction['reaction_info']['equation'],
                            'model_list': reaction['reaction_info']['model_list']
                        }
                        result['reactions'].append(reaction_data)

                # 处理代谢物结果
                if search_results.get('metabolites'):
                    for metabolite in search_results['metabolites']:
                        metabolite_data = {
                            'id': metabolite['metabolite_info']['id'],
                            'name': metabolite['metabolite_info']['name'],
                            'universal_id': metabolite['metabolite_info']['universal_id'],
                            'formula': metabolite['metabolite_info']['formula'],
                            'reactions': []
                        }
                        if metabolite.get('reactions'):
                            for reaction in metabolite['reactions']:
                                metabolite_data['reactions'].append({
                                    'reaction_id': reaction['reaction_id'],
                                    'name': reaction['name'],
                                    'reaction_string': reaction['reaction_string'],
                                    'model_list': reaction['model_list']
                                })
                        result['metabolites'].append(metabolite_data)

                # 处理基因结果
                if search_results.get('genes'):
                    for gene in search_results['genes']:
                        gene_data = {
                            'id': gene['id'],
                            'name': gene['name'],
                            'model_list': gene['model_list'],
                            'reactions': []
                        }
                        if gene.get('reactions'):
                            for reaction in gene['reactions'][:10]:  # 限制返回前10个反应
                                reaction_data = {
                                    'id': reaction['id'],
                                    'name': reaction['name'],
                                    'gpr_info': []
                                }
                                if reaction.get('gpr_info'):
                                    for gpr_item in reaction['gpr_info']:
                                        reaction_data['gpr_info'].append({
                                            'gpr': gpr_item['gpr'],
                                            'models': gpr_item['models']
                                        })
                                gene_data['reactions'].append(reaction_data)
                        result['genes'].append(gene_data)

                # 处理NaN值
                result = nan_to_none(result)
                return jsonify(result)

            except Exception as e:
                return jsonify({'error': str(e)}), 500
        else:
            # 表单提交（网页请求）
            form = UnifiedSearchForm()
            search_results = None
            error = None

            # 动态填充模型选择
            try:
                from BIGG.model_analyzer import get_available_models_cached  # type: ignore
                available_models = get_available_models_cached()
                form.model_filter.choices = [('', 'All Models')] + [(model, model) for model in available_models]
            except Exception as e:
                print(f"Warning: Could not load models for filter: {e}")
                form.model_filter.choices = [('', 'All Models')]

            if form.validate_on_submit():
                query = form.query.data.strip()
                model_filter = form.model_filter.data

                try:
                    # 调用统一搜索功能，传递模型过滤参数
                    model_filter_list = [model_filter] if model_filter else None
                    search_results = search_database_structured(query, model_filter=model_filter_list)
                except Exception as e:
                    error = f"Search error: {str(e)}"
                    search_results = None

            return render_template('bigg.html', form=form, search_results=search_results, error=error)

    @app.route('/prediction', methods=['GET', 'POST'])
    def prediction():
        form = ReactionForm()
        if form.validate_on_submit():
            reaction = form.reaction.data
            dg = calculate_dg(reaction)
            return render_template('prediction.html', form=form, dg=dg, reaction=reaction)
        return render_template('prediction.html', form=form)

    @app.route('/parse_equation_route', methods=['POST'])
    def parse_equation_route():
        try:
            equation = request.form.get('equation', '').strip()
            if ' = ' not in equation:
                return jsonify({'error': 'Equation must contain " = " separator'}), 400

            # 直接使用utils.py中的函数
            compound_names, stoichiometries = parse_equation(equation)
            return jsonify({'compounds': compound_names, 'stoichiometries': stoichiometries})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/calculate', methods=['POST'])
    @rate_limit(limit_per_hour=500)  # 单个反应预测：每小时500次
    def calculate():
        try:
            # 支持JSON和表单数据
            if request.is_json:
                data = request.get_json()
                reaction_condition = data.get('reaction_condition')
                equation = data.get('equation')
                identifier = data.get('identifier_type')
                # 添加对JSON custom_condition的支持
                json_custom_condition = data.get('custom_condition') if reaction_condition == 'custom' else None
            else:
                # 验证必需参数（仅对表单数据）
                for param in ['reaction_condition', 'equation', 'identifier_type']:
                    if not request.form.get(param):
                        return jsonify({'error': f'Missing required parameter: {param}'}), 400
                reaction_condition = request.form.get('reaction_condition')
                equation = request.form.get('equation')
                identifier = request.form.get('identifier_type')

            # 验证参数
            if not all([reaction_condition, equation, identifier]):
                return jsonify({'error': 'Missing required parameters: reaction_condition, equation, identifier_type'}), 400

            custom_condition = None
            if reaction_condition == 'custom':
                # 优先使用JSON中的custom_condition
                if request.is_json and json_custom_condition:
                    custom_condition = json_custom_condition
                # 检查是否有全局自定义条件参数（表单数据）
                elif all(key in request.form for key in ['global_pH', 'global_I', 'global_pMg', 'global_e_potential']):
                    custom_condition = {
                        'pH': float(request.form.get('global_pH')),
                        'I': float(request.form.get('global_I')),
                        'pMg': float(request.form.get('global_pMg')),
                        'e_potential': float(request.form.get('global_e_potential'))
                    }
                else:
                    # 使用单个化合物自定义条件
                    compound_names, stoichiometries = parse_equation(equation)

                    custom_conditions = {}
                    for index, compound in enumerate(compound_names):
                        pH = float(request.form.get(f'custom_conditions-{index}-pH', 7.0))
                        I = float(request.form.get(f'custom_conditions-{index}-I', 0.25))
                        pMg = float(request.form.get(f'custom_conditions-{index}-pMg', 14.0))
                        e_potential = float(request.form.get(f'custom_conditions-{index}-e_potential', 0.0))
                        custom_conditions[index] = {
                            'pH': pH,
                            'I': I,
                            'pMg': pMg,
                            'e_potential': e_potential
                        }
                    custom_condition = custom_conditions

            print(f"DEBUG: Request type: {'JSON' if request.is_json else 'FORM'}")
            print(f"DEBUG: Calling calculate_dg with equation={equation}, identifier={identifier}, reaction_condition={reaction_condition}, custom_condition={custom_condition}")
            result = calculate_dg(equation, identifier, reaction_condition, custom_condition)
            print(f"DEBUG: calculate_dg result: {result}")
            if 'error' in result:
                print(f"DEBUG: Error in result: {result['error']}")
                return jsonify({'error': result['error']}), 500

            # 处理NaN值
            result = nan_to_none(result)

            return jsonify({
                'dG_prime': result['dG_prime'],
                'dG_std_dev': result['dG_std_dev'],
                'message': 'Calculation completed successfully'
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/batch_calculate', methods=['POST'])
    @rate_limit(limit_per_hour=100)  # 批量预测：每小时100次（更保守）
    def batch_calculate():
        try:
            # 支持JSON和表单数据
            if request.is_json:
                data = request.get_json()
                if not data:
                    return jsonify({'error': 'JSON data required'}), 400
                equations = data.get('equations', '').strip().split('\n')
                identifier = data.get('identifier_type')
                reaction_condition = data.get('reaction_condition')
                custom_condition = data.get('custom_condition') if reaction_condition == 'custom' else None
            else:
                # 验证必需参数（仅对表单数据）
                for param in ['equations', 'identifier_type', 'reaction_condition']:
                    if not request.form.get(param):
                        return jsonify({'error': f'Missing required parameter: {param}'}), 400
                equations = request.form.get('equations', '').strip().split('\n')
                identifier = request.form.get('identifier_type')
                reaction_condition = request.form.get('reaction_condition')
                custom_condition = None
                if reaction_condition == 'custom':
                    custom_condition = {
                        'pH': float(request.form.get('global_pH', 7.0)),
                        'I': float(request.form.get('global_I', 0.25)),
                        'pMg': float(request.form.get('global_pMg', 14.0)),
                        'e_potential': float(request.form.get('global_e_potential', 0.0))
                    }

            results = []
            for equation in equations:
                equation = equation.strip()
                if not equation:
                    continue

                try:
                    result = calculate_dg(equation, identifier, reaction_condition, custom_condition)
                    if 'error' in result:
                        results.append({
                            'equation': equation,
                            'error': result['error'],
                            'status': 'error'
                        })
                    else:
                        # 处理 NaN 值 - 将其转换为 null 以确保 JSON 合法性
                        dG_prime = result['dG_prime']
                        dG_std_dev = result['dG_std_dev']

                        # 检查是否为 NaN 并转换为 null
                        import math
                        if dG_prime is not None and (isinstance(dG_prime, float) and math.isnan(dG_prime)):
                            dG_prime = None
                        if dG_std_dev is not None and (isinstance(dG_std_dev, float) and math.isnan(dG_std_dev)):
                            dG_std_dev = None

                        # 只检查 dG_prime 是否有效，dG_std_dev 为 null 不影响结果
                        if dG_prime is None:
                            results.append({
                                'equation': equation,
                                'error': 'Missing data in database',
                                'status': 'error'
                            })
                        else:
                            results.append({
                                'equation': equation,
                                'dG_prime': dG_prime,
                                'dG_std_dev': dG_std_dev,
                                'status': 'success'
                            })
                except Exception as e:
                    results.append({
                        'equation': equation,
                        'error': str(e),
                        'status': 'error'
                    })

            return jsonify({
                'results': results,
                'message': 'Batch calculation completed'
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api', methods=['GET'])
    def api():
        return render_template('api.html')

    @app.route('/citation')
    def citation():
        return render_template('citation.html')

    @app.route('/faq')
    def faq():
        return render_template('faq.html')

    @app.route('/help')
    def help():
        return render_template('help.html')

    @app.route('/loading_status')
    def loading_status():
        """返回数据加载状态（简化版）"""
        return jsonify({
            'loaded': True,  # 启动预热后即可认为已加载
            'message': 'Data ready'
        })

    @app.route('/get_reaction_dg_data/<reaction_id>')
    def get_reaction_dg_data_route(reaction_id):
        """获取特定reaction的ΔG数据"""
        try:
            from BIGG.reaction_analyzer import get_reaction_dg_data  # type: ignore

            # 从请求参数中获取model_list
            model_list_str = request.args.get('model_list', '')
            model_list = None
            if model_list_str:
                model_list = [model.strip() for model in model_list_str.split(',')]

            dg_data = get_reaction_dg_data(reaction_id, model_list=model_list)
            dg_data = nan_to_none(dg_data)
            # print('dg_data:', dg_data)  # 注释掉详细数据输出
            return jsonify({ 
                'success': True,
                'reaction_id': reaction_id,
                'models_data': dg_data
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    # ==================== 新的结构化API端点 ====================

    @app.route('/api/models', methods=['GET'])
    @rate_limit(limit_per_hour=300)
    @handle_errors
    def api_models():
        """搜索模型并返回详细信息"""
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify({'error': 'Query parameter "q" is required'}), 400

        try:
            from BIGG.model_analyzer import get_available_models_cached, search_by_model_structured  # type: ignore

            # 获取所有可用模型
            available_models = get_available_models_cached()

            # 搜索匹配的模型
            model_matches = [model for model in available_models if query.lower() in model.lower()]

            if not model_matches:
                return jsonify({
                    'query': query,
                    'models': [],
                    'total_found': 0
                })

            # 获取模型详细信息
            models_data = []
            for model_id in model_matches:
                try:
                    bigg_path = os.path.join(os.path.dirname(__file__), '..', 'BIGG')
                    data_dir = os.path.join(bigg_path, 'result')
                    model_info = search_by_model_structured(model_id, data_dir)

                    if model_info:
                        model_data = {
                            'model_id': model_info['model_id'],
                            'download_url': f"/api/models/{model_info['model_id']}/download",
                            'stats': model_info.get('model_stats'),
                            'conditions': {}
                        }

                        # 添加条件信息
                        if model_info.get('conditions'):
                            for comp, cond in model_info['conditions'].items():
                                model_data['conditions'][comp] = {
                                    'pH': cond['pH'],
                                    'T': cond['T'],
                                    'I': cond['I'],
                                    'pMg': cond['pMg'],
                                    'e_potential': cond['e_potential']
                                }

                        models_data.append(model_data)
                except Exception as e:
                    print(f"Error processing model {model_id}: {e}")
                    continue

            result = nan_to_none({
                'query': query,
                'models': models_data,
                'total_found': len(models_data)
            })

            return jsonify(result)

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/models/<model_id>', methods=['GET'])
    @rate_limit(limit_per_hour=300)
    @handle_errors
    def api_model_detail(model_id):
        """获取特定模型的详细信息"""
        try:
            from BIGG.model_analyzer import search_by_model_structured  # type: ignore

            bigg_path = os.path.join(os.path.dirname(__file__), '..', 'BIGG')
            data_dir = os.path.join(bigg_path, 'result')
            model_info = search_by_model_structured(model_id, data_dir)

            if not model_info:
                return jsonify({'error': f'Model "{model_id}" not found'}), 404

            model_data = {
                'model_id': model_info['model_id'],
                'download_url': f"/api/models/{model_info['model_id']}/download",
                'stats': model_info.get('model_stats'),
                'conditions': {}
            }

            # 添加条件信息
            if model_info.get('conditions'):
                for comp, cond in model_info['conditions'].items():
                    model_data['conditions'][comp] = {
                        'pH': cond['pH'],
                        'T': cond['T'],
                        'I': cond['I'],
                        'pMg': cond['pMg'],
                        'e_potential': cond['e_potential']
                    }

            result = nan_to_none(model_data)
            return jsonify(result)

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/models/<model_id>/download', methods=['GET'])
    def api_model_download(model_id):
        """下载模型的ΔG数据文件"""
        # 绝对路径
        bigg_dir = os.path.join(os.path.dirname(__file__), '..', 'BIGG', 'result')
        filename = f"{model_id}_standard_dGr_dGbyG.csv"
        return send_from_directory(bigg_dir, filename, as_attachment=True)

    @app.route('/api/reactions', methods=['GET'])
    @rate_limit(limit_per_hour=300)
    @handle_errors
    def api_reactions():
        """搜索反应并直接返回包含ΔG数据的结果"""
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify({'error': 'Query parameter "q" is required'}), 400

        model_filter = request.args.get('model_filter')
        include_dg = request.args.get('include_dg', 'true').lower() == 'true'

        try:
            from BIGG.reaction_analyzer import search_by_reaction_structured, get_reaction_dg_data  # type: ignore

            # 搜索反应
            model_filter_list = [model_filter] if model_filter else None
            reactions = search_by_reaction_structured(query, model_filter=model_filter_list)

            if not reactions:
                return jsonify({
                    'query': query,
                    'reactions': [],
                    'total_found': 0,
                    'model_filter': model_filter
                })

            # 处理反应数据并包含ΔG信息
            reactions_data = []
            for reaction in reactions:
                reaction_data = {
                    'id': reaction['reaction_info']['id'],
                    'name': reaction['reaction_info']['name'],
                    'equation': reaction['reaction_info']['equation'],
                    'model_list': list(reaction['reaction_info']['model_list']),
                    'dg_data': []
                }

                # 如果需要包含ΔG数据，则获取
                if include_dg:
                    try:
                        dg_data = get_reaction_dg_data(
                            reaction['reaction_info']['id'],
                            model_list=model_filter_list
                        )
                        reaction_data['dg_data'] = dg_data
                    except Exception as e:
                        print(f"Error getting ΔG data for {reaction['reaction_info']['id']}: {e}")
                        reaction_data['dg_data'] = []

                reactions_data.append(reaction_data)

            result = nan_to_none({
                'query': query,
                'reactions': reactions_data,
                'total_found': len(reactions_data),
                'model_filter': model_filter,
                'include_dg': include_dg
            })

            return jsonify(result)

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/metabolites', methods=['GET'])
    @rate_limit(limit_per_hour=300)
    @handle_errors
    def api_metabolites():
        """搜索代谢物并返回相关反应及ΔG数据"""
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify({'error': 'Query parameter "q" is required'}), 400

        model_filter = request.args.get('model_filter')
        include_dg = request.args.get('include_dg', 'true').lower() == 'true'

        try:
            from BIGG.reaction_analyzer import search_metabolites_by_query_structured, get_reaction_dg_data  # type: ignore

            # 搜索代谢物
            model_filter_list = [model_filter] if model_filter else None
            metabolites = search_metabolites_by_query_structured(query, model_filter=model_filter_list)

            if not metabolites:
                return jsonify({
                    'query': query,
                    'metabolites': [],
                    'total_found': 0,
                    'model_filter': model_filter
                })

            # 处理代谢物数据
            metabolites_data = []
            for metabolite in metabolites:
                metabolite_data = {
                    'id': metabolite['metabolite_info']['id'],
                    'name': metabolite['metabolite_info']['name'],
                    'universal_id': metabolite['metabolite_info']['universal_id'],
                    'formula': metabolite['metabolite_info']['formula'],
                    'reactions': []
                }

                # 处理相关反应
                if metabolite.get('reactions'):
                    for reaction in metabolite['reactions']:
                        reaction_data = {
                            'reaction_id': reaction['reaction_id'],
                            'name': reaction['name'],
                            'equation': reaction['equation'],
                            'model_list': list(reaction['model_list']),
                            'dg_data': []
                        }

                        # 如果需要包含ΔG数据，则获取
                        if include_dg:
                            try:
                                dg_data = get_reaction_dg_data(
                                    reaction['reaction_id'],
                                    model_list=model_filter_list
                                )
                                reaction_data['dg_data'] = dg_data
                            except Exception as e:
                                print(f"Error getting ΔG data for {reaction['reaction_id']}: {e}")
                                reaction_data['dg_data'] = []

                        metabolite_data['reactions'].append(reaction_data)

                metabolites_data.append(metabolite_data)

            result = nan_to_none({
                'query': query,
                'metabolites': metabolites_data,
                'total_found': len(metabolites_data),
                'model_filter': model_filter,
                'include_dg': include_dg
            })

            return jsonify(result)

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/genes', methods=['GET'])
    @rate_limit(limit_per_hour=300)
    @handle_errors
    def api_genes():
        """搜索基因并返回相关信息"""
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify({'error': 'Query parameter "q" is required'}), 400

        model_filter = request.args.get('model_filter')
        max_reactions = int(request.args.get('max_reactions', '10'))  # 限制返回的反应数量

        try:
            from BIGG.reaction_analyzer import find_genes_by_query  # type: ignore

            # 搜索基因
            model_filter_list = [model_filter] if model_filter else None
            genes = find_genes_by_query(query, model_filter=model_filter_list)

            if not genes:
                return jsonify({
                    'query': query,
                    'genes': [],
                    'total_found': 0,
                    'model_filter': model_filter
                })

            # 处理基因数据
            genes_data = []
            for gene in genes:
                gene_data = {
                    'id': gene['id'],
                    'name': gene['name'],
                    'model_list': list(gene['model_list']),
                    'reactions': [],
                    'total_reactions': len(gene['reactions']) if gene.get('reactions') else 0
                }

                # 处理相关反应（限制数量）
                if gene.get('reactions'):
                    for reaction in gene['reactions'][:max_reactions]:
                        reaction_data = {
                            'id': reaction['id'],
                            'name': reaction['name'],
                            'gpr_info': []
                        }

                        # 处理GPR信息
                        if reaction.get('gpr_info'):
                            for gpr_item in reaction['gpr_info']:
                                reaction_data['gpr_info'].append({
                                    'gpr': gpr_item['gpr'],
                                    'models': list(gpr_item['models'])
                                })

                        gene_data['reactions'].append(reaction_data)

                genes_data.append(gene_data)

            result = nan_to_none({
                'query': query,
                'genes': genes_data,
                'total_found': len(genes_data),
                'model_filter': model_filter,
                'max_reactions_per_gene': max_reactions
            })

            return jsonify(result)

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ==================== 原有端点保持不变 ====================

    @app.route('/warmup')
    def warmup():
        """预热端点，预加载必要数据"""
        try:
            # 触发BiGG模型数据加载
            from BIGG.model_analyzer import get_available_models_cached  # type: ignore
            models = get_available_models_cached()

            # 触发搜索数据加载
            from unified_search_structured import search_database_structured  # type: ignore
            search_results = search_database_structured("LDHC")

            return f"Warmup OK: {len(models)} models, {len(search_results)} LDHC results"
        except Exception as e:
            return f"Warmup failed: {str(e)}", 500

    @app.route('/health')
    def health():
        """轻量级健康检查端点 - 仅检查数据结构是否就绪"""
        try:
            # 检查BiGG数据是否加载（轻量级检查）
            from BIGG.reaction_analyzer import _DF_PART, _DF_RXN, _DF_MET, _MODELS

            # 基础结构检查
            bigg_loaded = all(x is not None for x in (_DF_PART, _DF_RXN, _DF_MET, _MODELS))

            if bigg_loaded:
                # 轻量级数据检查：只验证数据框非空
                data_valid = (
                    len(_DF_RXN) > 0 and
                    len(_DF_MET) > 0 and
                    len(_MODELS) > 0
                )

                if data_valid:
                    # 轻量级dGbyG检查：仅检查模块是否可导入
                    dgbyg_available = False
                    try:
                        import dGbyG.api  # 不执行计算，只检查导入
                        dgbyg_available = True
                    except ImportError:
                        pass  # Docker环境外预期的行为

                    return jsonify({
                        'status': 'healthy',
                        'bigg_loaded': True,
                        'models_count': len(_MODELS),
                        'reactions_count': len(_DF_RXN),
                        'dgbyg_available': dgbyg_available
                    })
                else:
                    return jsonify({
                        'status': 'warming_up',
                        'message': 'Data loaded but empty'
                    }), 503
            else:
                return jsonify({
                    'status': 'warming_up',
                    'message': 'BiGG data still loading'
                }), 200

        except Exception as e:
            return jsonify({
                'status': 'unhealthy',
                'error': str(e)
            }), 503

