import streamlit as st
import pandas as pd
import json
import os
import shutil
from datetime import datetime
from dateutil.relativedelta import relativedelta
import uuid
import plotly.express as px
import yfinance as yf
from filelock import FileLock # Para segurança dos dados concorrentes

# --- 1. CONFIGURAÇÃO GERAL E CONSTANTES ---

st.set_page_config(page_title="Gestor Financeiro PRO", layout="wide", initial_sidebar_state="expanded")
st.title("💰 Gestor Financeiro PRO")

# Nomes dos arquivos de dados
DATA_DIR = 'data'
LANCAMENTOS_FILE = os.path.join(DATA_DIR, 'lancamentos.json')
INVESTIMENTOS_FILE = os.path.join(DATA_DIR, 'investimentos.json')
METAS_FILE = os.path.join(DATA_DIR, 'metas.json')
RECORRENTES_FILE = os.path.join(DATA_DIR, 'recorrentes.json')
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')


# --- 2. FUNÇÕES DE GERENCIAMENTO DE DADOS (CRUD, CACHE, LOCK) ---

def setup_data_files():
    """Cria o diretório 'data' e os arquivos JSON necessários se não existirem."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    for file_path in [LANCAMENTOS_FILE, INVESTIMENTOS_FILE, METAS_FILE, RECORRENTES_FILE, CONFIG_FILE]:
        if not os.path.exists(file_path):
            with open(file_path, 'w', encoding='utf-8') as f:
                # O arquivo de config é um dicionário, os outros são listas
                json.dump({} if file_path == CONFIG_FILE else [], f)

@st.cache_data(ttl=60) # Cache por 60 segundos para evitar leituras excessivas
def load_data(file_path, is_dict=False):
    """Carrega dados de um arquivo JSON. Retorna um dicionário ou lista vazia em caso de erro."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {} if is_dict else []

def save_data(data, file_path):
    """Salva dados em um arquivo JSON de forma segura, usando FileLock e limpando o cache."""
    lock_path = f"{file_path}.lock"
    lock = FileLock(lock_path)
    with lock:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    # Limpa o cache para a função load_data correspondente
    is_dict_arg = file_path == CONFIG_FILE
    st.cache_data.clear()


# --- 3. LÓGICA DE INICIALIZAÇÃO E PROCESSAMENTO AUTOMÁTICO ---

# Garante que os arquivos de dados existam antes de qualquer outra operação
setup_data_files()

# Inicialização do estado da sessão para controle de edição, etc.
SESSION_DEFAULTS = {
    'editing_lancamento_id': None,
    'editing_investimento_id': None,
    'editing_meta_id': None,
    'editing_recorrente_id': None,
}
for key, value in SESSION_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

def criar_backup_diario():
    """Cria uma cópia de segurança diária dos principais arquivos de dados."""
    config = load_data(CONFIG_FILE, is_dict=True)
    hoje_str = datetime.now().strftime('%Y-%m-%d')
    if config.get('ultimo_backup') != hoje_str:
        backup_dir = os.path.join(DATA_DIR, 'backup')
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        files_to_backup = [LANCAMENTOS_FILE, INVESTIMENTOS_FILE, RECORRENTES_FILE, METAS_FILE]
        for file_path in files_to_backup:
            if os.path.exists(file_path):
                base_name = os.path.basename(file_path)
                backup_path = os.path.join(backup_dir, f"{base_name}_{hoje_str}.json")
                shutil.copy(file_path, backup_path)
        
        config['ultimo_backup'] = hoje_str
        save_data(config, CONFIG_FILE)
        st.toast("Backup diário dos dados criado com sucesso!")

def processar_recorrentes():
    """Verifica e cria lançamentos recorrentes para o mês atual, se ainda não foram criados."""
    recorrentes = load_data(RECORRENTES_FILE)
    lancamentos = load_data(LANCAMENTOS_FILE)
    config = load_data(CONFIG_FILE, is_dict=True)
    
    hoje = datetime.now()
    mes_atual_str = hoje.strftime('%Y-%m')
    ultimo_mes_processado = config.get('ultimo_mes_recorrente', '')

    if ultimo_mes_processado != mes_atual_str and recorrentes:
        novos_lancamentos = []
        for recorrente in recorrentes:
            dia_criacao = int(recorrente['data_base'].split('-')[2])
            # Garante que o dia do lançamento não seja inválido (ex: dia 31 em fevereiro)
            dia_lancamento = min(dia_criacao, pd.Timestamp(mes_atual_str).days_in_month)
            data_lancamento_mes_atual = hoje.replace(day=dia_lancamento).strftime('%Y-%m-%d')
            
            novo_lancamento = {
                "id": str(uuid.uuid4()),
                "data": data_lancamento_mes_atual,
                "tipo": recorrente['tipo'],
                "categoria": recorrente['categoria'],
                "valor": recorrente['valor'],
                "descricao": f"(Recorrente) {recorrente['categoria']}"
            }
            novos_lancamentos.append(novo_lancamento)
            
        if novos_lancamentos:
            lancamentos.extend(novos_lancamentos)
            save_data(lancamentos, LANCAMENTOS_FILE)
            config['ultimo_mes_recorrente'] = mes_atual_str
            save_data(config, CONFIG_FILE)
            st.toast(f"{len(novos_lancamentos)} lançamentos recorrentes adicionados!")
            st.rerun()

# Executa as rotinas de inicialização
criar_backup_diario()
processar_recorrentes()


# --- 4. DEFINIÇÃO DAS PÁGINAS DO APLICATIVO ---

def page_lancamentos():
    st.header("Gerenciar Lançamentos")
    lancamentos = load_data(LANCAMENTOS_FILE)
    recorrentes = load_data(RECORRENTES_FILE)
    
    item_para_editar = next((item for item in lancamentos if item['id'] == st.session_state.editing_lancamento_id), None) if st.session_state.editing_lancamento_id else None
    rec_para_editar = next((item for item in recorrentes if item['id'] == st.session_state.editing_recorrente_id), None) if st.session_state.editing_recorrente_id else None

    tab1, tab2 = st.tabs(["Lançamentos do Mês", "Lançamentos Recorrentes"])

    with tab1:
        with st.expander("➕ Adicionar ou Editar Lançamento", expanded=(item_para_editar is not None)):
            with st.form(key="lancamento_form"):
                default = lambda key, val: item_para_editar[key] if item_para_editar else val
                tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True, index=["Despesa", "Receita"].index(default('tipo', 'Despesa')))
                data_lancamento = st.date_input("Data", value=datetime.strptime(default('data', datetime.now().strftime('%Y-%m-%d')), '%Y-%m-%d'))
                categoria = st.text_input("Categoria", placeholder="Ex: Aluguel, Salário, Investimento", value=default('categoria', ''))
                valor = st.number_input("Valor (R$)", min_value=0.01, format="%.2f", value=default('valor', 0.01))
                
                submitted = st.form_submit_button("✅ Salvar")
                if submitted:
                    if not categoria or valor <= 0:
                        st.error("Campos Categoria e Valor são obrigatórios.")
                    else:
                        if item_para_editar:
                            item_para_editar.update({"data": data_lancamento.strftime('%Y-%m-%d'), "tipo": tipo, "categoria": categoria.strip(), "valor": valor})
                            st.success("Lançamento atualizado!")
                        else:
                            lancamentos.append({"id": str(uuid.uuid4()), "data": data_lancamento.strftime('%Y-%m-%d'), "tipo": tipo, "categoria": categoria.strip(), "valor": valor, "descricao": ""})
                            st.success("Lançamento adicionado!")
                        
                        save_data(lancamentos, LANCAMENTOS_FILE)
                        st.session_state.editing_lancamento_id = None
                        st.rerun()

        st.subheader("Histórico de Lançamentos")
        lancamentos_ordenados = sorted(lancamentos, key=lambda x: x['data'], reverse=True)
        
        # CORREÇÃO PRINCIPAL: Iterar sobre uma cópia da lista para permitir a exclusão segura.
        for item in lancamentos_ordenados.copy():
            col1, col2, col3 = st.columns([5, 3, 2])
            with col1:
                st.markdown(f"**{item['categoria']}**")
                st.caption(f"{item['data']} | {item['tipo']}")
            with col2:
                cor = "red" if item['tipo'] == 'Despesa' else 'green'
                st.markdown(f"<h4 style='text-align: right; color: {cor};'>R$ {item.get('valor', 0):,.2f}</h4>", unsafe_allow_html=True)
            with col3:
                sub_col1, sub_col2 = st.columns(2)
                if sub_col1.button("✏️", key=f"edit_lanc_{item['id']}", help="Editar lançamento", use_container_width=True):
                    st.session_state.editing_lancamento_id = item['id']
                    st.rerun()
                if sub_col2.button("🗑️", key=f"del_lanc_{item['id']}", help="Excluir lançamento", use_container_width=True):
                    lancamentos.remove(item)
                    save_data(lancamentos, LANCAMENTOS_FILE)
                    st.rerun()
            st.divider()

    with tab2:
        st.subheader("Gerenciar Lançamentos Recorrentes")
        with st.expander("➕ Adicionar ou Editar Lançamento Recorrente", expanded=(rec_para_editar is not None)):
            with st.form(key="recorrente_form"):
                default_rec = lambda key, val: rec_para_editar[key] if rec_para_editar else val
                tipo_rec = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True, key="tipo_rec", index=["Despesa", "Receita"].index(default_rec('tipo', 'Despesa')))
                categoria_rec = st.text_input("Categoria", value=default_rec('categoria', ''))
                valor_rec = st.number_input("Valor (R$)", min_value=0.01, format="%.2f", value=default_rec('valor', 0.01))
                submitted_rec = st.form_submit_button("✅ Salvar Recorrente")
                if submitted_rec:
                    if not categoria_rec or valor_rec <= 0:
                        st.error("Campos Categoria e Valor são obrigatórios.")
                    else:
                        if rec_para_editar:
                            rec_para_editar.update({"tipo": tipo_rec, "categoria": categoria_rec.strip(), "valor": valor_rec})
                            st.success("Recorrente atualizado!")
                        else:
                            recorrentes.append({"id": str(uuid.uuid4()), "tipo": tipo_rec, "categoria": categoria_rec.strip(), "valor": valor_rec, "data_base": datetime.now().strftime('%Y-%m-%d')})
                            st.success("Recorrente salvo!")
                        
                        save_data(recorrentes, RECORRENTES_FILE)
                        st.session_state.editing_recorrente_id = None
                        st.rerun()
        
        st.markdown("---")
        if not recorrentes:
            st.info("Nenhum lançamento recorrente cadastrado.")
        
        # CORREÇÃO PRINCIPAL: Iterar sobre uma cópia da lista para permitir a exclusão segura.
        for item in recorrentes.copy():
            col1, col2, col3 = st.columns([5, 3, 2])
            with col1:
                st.markdown(f"**{item['categoria']}** ({item['tipo']})")
            with col2:
                st.markdown(f"<h5 style='text-align: right;'>R$ {item['valor']:,.2f}</h5>", unsafe_allow_html=True)
            with col3:
                sub_col1, sub_col2 = st.columns(2)
                if sub_col1.button("✏️", key=f"edit_rec_{item['id']}", help="Editar recorrente", use_container_width=True):
                    st.session_state.editing_recorrente_id = item['id']
                    st.rerun()
                if sub_col2.button("🗑️", key=f"del_rec_{item['id']}", help="Excluir recorrente", use_container_width=True):
                    recorrentes.remove(item)
                    save_data(recorrentes, RECORRENTES_FILE)
                    st.rerun()
            st.divider()

def page_dashboard():
    st.header("Dashboard Financeiro")
    lancamentos = load_data(LANCAMENTOS_FILE)
    if not lancamentos:
        st.info("Nenhum lançamento para exibir. Adicione um na página 'Lançamentos'.")
        return
    
    df = pd.DataFrame(lancamentos)
    df['valor'] = pd.to_numeric(df['valor'])
    df['data'] = pd.to_datetime(df['data'])
    df['mes'] = df['data'].dt.strftime('%Y-%m')
    df['ano'] = df['data'].dt.year

    view_type = st.radio("Visualizar por:", ["Mês", "Ano"], horizontal=True, key="dashboard_view")
    
    if view_type == "Mês":
        meses_disponiveis = sorted(df['mes'].unique(), reverse=True)
        if not meses_disponiveis:
            st.warning("Não há dados para o período selecionado.")
            return
        mes_selecionado = st.selectbox("Selecione o Mês:", meses_disponiveis)
        df_filt = df[df['mes'] == mes_selecionado]
    else:
        anos_disponiveis = sorted(df['ano'].unique(), reverse=True)
        if not anos_disponiveis:
            st.warning("Não há dados para o período selecionado.")
            return
        ano_selecionado = st.selectbox("Selecione o Ano:", anos_disponiveis)
        df_filt = df[df['ano'] == ano_selecionado]

    receitas = df_filt[df_filt['tipo'] == 'Receita']['valor'].sum()
    despesas = df_filt[df_filt['tipo'] == 'Despesa']['valor'].sum()
    saldo = receitas - despesas

    col1, col2, col3 = st.columns(3)
    col1.metric("✅ Receitas", f"R$ {receitas:,.2f}")
    col2.metric("❌ Despesas", f"R$ {despesas:,.2f}")
    col3.metric("💰 Saldo", f"R$ {saldo:,.2f}")
    st.divider()

    col_chart1, col_chart2 = st.columns(2)
    with col_chart1:
        st.subheader("Distribuição de Despesas")
        df_despesas = df_filt[df_filt['tipo'] == 'Despesa']
        if not df_despesas.empty:
            fig = px.pie(df_despesas, values='valor', names='categoria', hole=.3, title="Despesas por Categoria")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Nenhuma despesa no período.")

    with col_chart2:
        st.subheader("Evolução Mensal (Receita x Despesa)")
        df_evolucao = df.groupby(['mes', 'tipo'])['valor'].sum().unstack(fill_value=0).reset_index()
        if not df_evolucao.empty:
            fig2 = px.bar(df_evolucao, x='mes', y=['Receita', 'Despesa'], barmode='group', title="Receitas vs Despesas por Mês")
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Sem dados para o gráfico de evolução.")
    
    st.divider()
    st.subheader("Exportar Dados")
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Baixar Lançamentos como CSV", data=csv, file_name='lancamentos.csv', mime='text/csv')

@st.cache_data(ttl=1800) # Cache de cotações por 30 minutos
def buscar_cotacoes(tickers):
    if not tickers:
        return {}
    tickers_sa = [f"{ticker.strip().upper()}.SA" for ticker in tickers]
    try:
        data = yf.download(tickers_sa, period='1d', progress=False, auto_adjust=True)
        if data.empty:
            return {}
        
        prices = {}
        # Lida com o caso de um único ticker, onde o formato do DataFrame é diferente
        if len(tickers_sa) == 1:
            if not data.empty and 'Close' in data.columns:
                last_price = data['Close'].iloc[-1]
                if pd.notna(last_price):
                    prices[tickers[0]] = last_price
        else: # Múltiplos tickers
            for ticker_sa in tickers_sa:
                ticker_original = ticker_sa.replace('.SA', '')
                if ticker_sa in data['Close'].columns and pd.notna(data['Close'][ticker_sa].iloc[-1]):
                    prices[ticker_original] = data['Close'][ticker_sa].iloc[-1]
        return prices
    except Exception as e:
        # st.error(f"Erro ao buscar cotações: {e}") # Descomente para depuração
        return {}

def page_investimentos():
    st.header("Carteira de Investimentos")
    investimentos = load_data(INVESTIMENTOS_FILE)
    
    st.subheader("📈 Posição Consolidada")
    if not investimentos:
        st.info("Sua carteira está vazia. Adicione ativos no formulário abaixo.")
    else:
        tickers = [item['ticker'] for item in investimentos if item.get('classe') in ['Ações', 'FIIs']]
        cotacoes = buscar_cotacoes(tickers)
        
        total_custo = sum(item['quantidade'] * item['preco_medio'] for item in investimentos)
        valor_mercado_total = 0
        
        for item in investimentos:
            # Para ativos sem cotação online, o valor de mercado é considerado igual ao custo
            preco_atual = cotacoes.get(item['ticker'], item['preco_medio'])
            valor_mercado_total += item['quantidade'] * preco_atual
            
        lucro_prejuizo = valor_mercado_total - total_custo
        lucro_prejuizo_perc = (lucro_prejuizo / total_custo * 100) if total_custo > 0 else 0
        
        col_inv1, col_inv2, col_inv3 = st.columns(3)
        col_inv1.metric("Patrimônio (Custo)", f"R$ {total_custo:,.2f}")
        col_inv2.metric("Patrimônio (Mercado)", f"R$ {valor_mercado_total:,.2f}")
        col_inv3.metric("Lucro/Prejuízo", f"R$ {lucro_prejuizo:,.2f}", f"{lucro_prejuizo_perc:.2f}%")
        
        df_inv = pd.DataFrame(investimentos)
        df_inv['total_custo'] = df_inv['quantidade'] * df_inv['preco_medio']
        fig_pie = px.pie(df_inv, values='total_custo', names='classe', title='Composição da Carteira (pelo Custo)')
        st.plotly_chart(fig_pie, use_container_width=True)
    
    st.divider()
    st.subheader("💼 Meus Ativos")
    item_para_editar = next((item for item in investimentos if item['id'] == st.session_state.editing_investimento_id), None) if st.session_state.editing_investimento_id else None
    with st.expander("➕ Adicionar ou Editar Ativo Manualmente", expanded=(st.session_state.editing_investimento_id is not None)):
        with st.form(key="investimento_form"):
            classes = ["Ações", "FIIs", "Internacional", "Renda Fixa", "Cripto", "Outros"]
            default = lambda key, val: item_para_editar[key] if item_para_editar else val
            
            ticker = st.text_input("Ticker / Ativo", value=default('ticker', ''))
            classe_idx = classes.index(default('classe', 'Ações')) if default('classe', 'Ações') in classes else 0
            classe = st.selectbox("Classe", options=classes, index=classe_idx)
            quantidade = st.number_input("Quantidade", min_value=0.0, format="%.8f", value=default('quantidade', 0.0))
            preco_medio = st.number_input("Preço Médio de Compra (R$)", min_value=0.01, format="%.2f", value=default('preco_medio', 0.01))
            
            submitted = st.form_submit_button("✅ Salvar Ativo")
            if submitted:
                if not ticker or quantidade <= 0 or preco_medio <= 0:
                    st.error("Preencha todos os campos corretamente.")
                else:
                    if item_para_editar:
                        item_para_editar.update({"ticker": ticker.upper().strip(), "classe": classe, "quantidade": quantidade, "preco_medio": preco_medio})
                        st.success("Ativo atualizado!")
                    else:
                        investimentos.append({"id": str(uuid.uuid4()), "ticker": ticker.upper().strip(), "classe": classe, "quantidade": quantidade, "preco_medio": preco_medio})
                        st.success("Ativo adicionado!")
                    
                    save_data(investimentos, INVESTIMENTOS_FILE)
                    st.session_state.editing_investimento_id = None
                    st.rerun()

    # CORREÇÃO PRINCIPAL: Iterar sobre uma cópia da lista para permitir a exclusão segura.
    for item in sorted(investimentos, key=lambda x: x['ticker']):
        col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
        with col1:
            st.markdown(f"**{item['ticker']}**")
            st.caption(f"{item['classe']} | {item['quantidade']} cotas")
        with col2:
            st.markdown(f"<p style='text-align: right;'>Total Custo</p><h5 style='text-align: right;'>R$ {item['quantidade'] * item['preco_medio']:,.2f}</h5>", unsafe_allow_html=True)
        with col3:
            st.markdown(f"<p style='text-align: right;'>Preço Médio</p><h5 style='text-align: right;'>R$ {item['preco_medio']:,.2f}</h5>", unsafe_allow_html=True)
        with col4:
            sub_col1, sub_col2 = st.columns(2)
            if sub_col1.button("✏️", key=f"edit_invest_{item['id']}", help="Editar Ativo", use_container_width=True):
                st.session_state.editing_investimento_id = item['id']
                st.rerun()
            if sub_col2.button("🗑️", key=f"del_invest_{item['id']}", help="Excluir Ativo", use_container_width=True):
                investimentos.remove(item)
                save_data(investimentos, INVESTIMENTOS_FILE)
                st.rerun()
        st.divider()

def page_metas():
    st.header("🎯 Metas Financeiras")
    st.caption("Cadastre suas metas e acompanhe o progresso lançando despesas com a categoria igual ao nome da meta.")
    metas = load_data(METAS_FILE)
    lancamentos = load_data(LANCAMENTOS_FILE)
    
    item_para_editar = next((m for m in metas if m['id'] == st.session_state.editing_meta_id), None) if st.session_state.editing_meta_id else None
    
    with st.expander("🎯 Adicionar ou Editar Meta", expanded=(item_para_editar is not None)):
        with st.form("meta_form"):
            default = lambda key, val: item_para_editar[key] if item_para_editar else val
            nome = st.text_input("Nome da Meta (Ex: Reserva de Emergência)", value=default('nome', ''))
            valor_alvo = st.number_input("Valor Alvo (R$)", min_value=1.0, value=default('valor_alvo', 1000.0), format="%.2f")
            
            submitted = st.form_submit_button("✅ Salvar Meta")
            if submitted:
                if not nome or valor_alvo <= 0:
                    st.error("Nome e Valor Alvo são obrigatórios.")
                else:
                    if item_para_editar:
                        item_para_editar.update({"nome": nome.strip(), "valor_alvo": valor_alvo})
                        st.success("Meta atualizada!")
                    else:
                        metas.append({"id": str(uuid.uuid4()), "nome": nome.strip(), "valor_alvo": valor_alvo})
                        st.success("Meta criada!")
                    
                    save_data(metas, METAS_FILE)
                    st.session_state.editing_meta_id = None
                    st.rerun()
                    
    st.markdown("---")
    if not metas:
        st.info("Nenhuma meta cadastrada. Crie uma acima para começar a acompanhar seu progresso!")
    
    # CORREÇÃO PRINCIPAL: Iterar sobre uma cópia da lista para permitir a exclusão segura.
    for meta in metas.copy():
        aportes_meta = sum(item['valor'] for item in lancamentos if meta['nome'].lower() in item.get('categoria', '').lower() and item['tipo'] == 'Despesa')
        progresso = (aportes_meta / meta['valor_alvo']) if meta['valor_alvo'] > 0 else 0
        
        st.subheader(meta['nome'])
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(f"**Alvo:** R$ {meta['valor_alvo']:,.2f} | **Alcançado:** R$ {aportes_meta:,.2f} ({progresso:.1%})")
            st.progress(progresso)
        with col2:
            sub_col1, sub_col2 = st.columns(2)
            if sub_col1.button("✏️", key=f"edit_meta_{meta['id']}", help="Editar Meta", use_container_width=True):
                st.session_state.editing_meta_id = meta['id']
                st.rerun()
            if sub_col2.button("🗑️", key=f"del_meta_{meta['id']}", help="Excluir Meta", use_container_width=True):
                metas.remove(meta)
                save_data(metas, METAS_FILE)
                st.rerun()
        st.divider()

def page_configuracoes():
    st.header("⚙️ Configurações")
    config = load_data(CONFIG_FILE, is_dict=True)
    
    st.subheader("🎯 Metas de Alocação de Investimentos (%)")
    st.caption("Defina o percentual alvo para cada classe de ativo em sua carteira.")
    
    metas_alocacao = config.get('metas_alocacao', {})
    classes = ["Ações", "FIIs", "Internacional", "Renda Fixa", "Cripto", "Outros"]
    total_meta = 0

    with st.form("alocacao_form"):
        # Cria colunas para um layout mais compacto
        col1, col2 = st.columns(2)
        cols = [col1, col2, col1, col2, col1, col2] # Alterna entre as colunas

        for i, classe in enumerate(classes):
            with cols[i]:
                valor_atual = float(metas_alocacao.get(classe, 0.0))
                metas_alocacao[classe] = st.number_input(f"% {classe}", min_value=0.0, max_value=100.0, value=valor_atual, step=5.0, key=f"meta_{classe}")
        
        # Calcula o total dentro do formulário para feedback imediato
        total_meta = sum(float(v) for v in metas_alocacao.values())

        if abs(total_meta - 100.0) > 0.1:
            st.warning(f"A soma das alocações deve ser 100%. (Soma atual: {total_meta:.1f}%)")
        else:
            st.success(f"Soma das alocações: {total_meta:.1f}%")

        if st.form_submit_button("Salvar Metas de Alocação"):
            # Garante que os valores sejam salvos como float
            config['metas_alocacao'] = {k: float(v) for k, v in metas_alocacao.items()}
            save_data(config, CONFIG_FILE)
            st.success("Configurações salvas com sucesso!")
            st.rerun()

# --- 5. ROTEADOR PRINCIPAL E EXECUÇÃO ---
st.sidebar.title("Navegação")
paginas = {
    "Dashboard": page_dashboard,
    "Lançamentos": page_lancamentos,
    "Investimentos": page_investimentos,
    "Metas Financeiras": page_metas,
    "Configurações": page_configuracoes,
}
escolha = st.sidebar.radio("Selecione a página:", paginas.keys())

# Executa a função da página selecionada
paginas[escolha]()