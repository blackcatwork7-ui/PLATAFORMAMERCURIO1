"""Mercúrio Credit AI - protótipo demonstrativo local."""
import io
import json
import os
import re
from decimal import Decimal, InvalidOperation

import fitz
import requests
import streamlit as st

st.set_page_config(page_title='Mercúrio Credit AI', page_icon='📑', layout='wide')
st.title('Mercúrio Credit AI')
st.caption('Protótipo V1 • Análise assistida de crédito • Revisão humana obrigatória')
st.warning('Ambiente de demonstração: use somente dados fictícios ou anonimizados até a validação jurídica, de segurança e de privacidade.')

SYSTEM = '''Você é um analista assistivo de crédito imobiliário da Mercúrio Capital.
Retorne SOMENTE um objeto JSON válido, com campos: resumo_executivo (string),
capacidade_pagamento (string), patrimonio_garantias (string), pontos_positivos (lista de strings),
riscos_pendencias (lista de strings), fontes_evidencias (lista de strings),
defesa_credito (string, máximo de 2000 caracteres), parecer_preliminar (string).
Regras mandatórias:
1. Nunca invente valores, rendas, proprietários, dívidas, score, ausência de restrições ou fontes.
2. Informe explicitamente 'não comprovado' quando faltarem evidências.
3. Ao mencionar números, cite o arquivo e a página de origem sempre que presentes.
4. Não apresente decisão de aprovação/reprovação automática. Parecer é preliminar e revisável.
5. Diferencie dado comprovado, declaração do solicitante e estimativa.
6. Analise elementos positivos e riscos de modo equilibrado. Não omita riscos relevantes para tornar a defesa persuasiva.
7. A defesa deve ser objetiva, profissional, no máximo 2000 caracteres, sem alegações não comprovadas.
8. Não considere a ausência de documento de Serasa/Bacen como consulta negativa.
9. Use português do Brasil.
'''

with st.sidebar:
    st.header('Configuração')
    api_key = st.text_input('Chave API do DeepSeek', type='password', value=os.getenv('DEEPSEEK_API_KEY', ''))
    model = st.selectbox('Modelo', ['deepseek-flash', 'deepseek-v4-pro'], index=0)
    st.caption('A chave fica somente nesta sessão de execução. Não é salva em arquivo pelo aplicativo.')
    st.markdown('API: https://api.deepseek.com')

col1, col2 = st.columns(2)
with col1:
    cliente = st.text_input('Cliente / Razão social', placeholder='Ex.: Empresa Exemplo Ltda.')
    finalidade = st.text_area('Finalidade do crédito', placeholder='Ex.: Capital de giro / término de obra')
    modalidade = st.selectbox('Modalidade', ['Home Equity', 'SFI', 'CRI', 'Capital de giro com garantia', 'Outra'])
with col2:
    credito = st.number_input('Crédito solicitado (R$)', min_value=0.0, value=1000000.0, step=100000.0)
    avaliacao = st.number_input('Valor estimado da garantia (R$)', min_value=0.0, value=0.0, step=100000.0)
    renda = st.number_input('Renda mensal comprovada (R$; 0 se não informada)', min_value=0.0, value=0.0, step=10000.0)
    parcela = st.number_input('Parcela estimada (R$; 0 se não calculada)', min_value=0.0, value=0.0, step=1000.0)

st.subheader('Indicadores determinísticos')
a, b, c = st.columns(3)
a.metric('LTV', f'{credito / avaliacao:.1%}' if avaliacao else 'Não calculável')
b.metric('Parcela / renda', f'{parcela / renda:.1%}' if renda and parcela else 'Não calculável')
c.metric('Renda de referência', f'R$ {credito / 1_000_000 * 60_000:,.0f}'.replace(',', '.') if credito else '—')
st.caption('Renda de referência = R$ 60 mil/mês por R$ 1 milhão solicitado. Regra interna ilustrativa; não equivale a crédito aprovado.')

files = st.file_uploader('Carregue PDFs com texto selecionável (limite inicial: 10 arquivos)', type=['pdf'], accept_multiple_files=True)
contexto = st.text_area('Informações complementares / narrativa declarada', placeholder='Diferencie fatos comprovados de informações fornecidas pelo cliente.')
consent = st.checkbox('Confirmo que os documentos são fictícios/anonimizados ou que existe autorização e base legal para seu envio ao DeepSeek.')


def extract_pdf(uploaded):
    raw = uploaded.getvalue()
    if len(raw) > 15 * 1024 * 1024:
        raise ValueError(f'{uploaded.name}: arquivo maior que 15 MB.')
    doc = fitz.open(stream=raw, filetype='pdf')
    page_texts = []
    for i, page in enumerate(doc):
        if i >= 80:
            break
        tx = page.get_text('text').strip()
        if tx:
            page_texts.append(f'[ARQUIVO: {uploaded.name} | PÁGINA: {i + 1}]\n{tx[:12000]}')
    return '\n\n'.join(page_texts)

if st.button('Gerar análise preliminar e defesa', type='primary'):
    if not consent:
        st.error('É necessário confirmar a autorização/base legal ou utilizar documentos anonimizados.')
    elif not api_key:
        st.error('Informe uma chave válida da API DeepSeek na barra lateral.')
    elif not cliente.strip():
        st.error('Informe o cliente.')
    elif len(files or []) > 10:
        st.error('Envie no máximo 10 PDFs por análise.')
    else:
        try:
            docs = []
            for up in files or []:
                tx = extract_pdf(up)
                if not tx:
                    st.warning(f'{up.name}: PDF sem texto extraível. Utilize OCR externo validado ou versão pesquisável.')
                else:
                    docs.append(tx)
            full_docs = '\n\n'.join(docs)
            if len(full_docs) > 90000:
                st.warning('Documentação extensa: texto limitado a 90 mil caracteres. Pode haver perda de páginas; divida a análise em lotes.')
                full_docs = full_docs[:90000]
            dados = {
                'cliente': cliente, 'finalidade_declarada': finalidade, 'modalidade': modalidade,
                'credito_solicitado': credito, 'valor_garantia_estimado': avaliacao or None,
                'renda_mensal_comprovada_informada_pelo_operador': renda or None,
                'parcela_estimada': parcela or None,
                'ltv': credito / avaliacao if avaliacao else None,
                'comprometimento': parcela / renda if parcela and renda else None,
                'renda_referencia_interna': credito / 1_000_000 * 60000,
                'narrativa_operador': contexto, 'documentos_com_referencias': full_docs or 'Não fornecidos',
            }
            with st.spinner('Analisando...'):
                resp = requests.post(
                    'https://api.deepseek.com/chat/completions',
                    headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                    json={'model': model, 'thinking': {'type':'disabled'}, 'temperature': 0.2,
                          'response_format': {'type': 'json_object'}, 'max_tokens': 3500,
                          'messages': [{'role': 'system', 'content': SYSTEM},
                                       {'role': 'user', 'content': 'Produza o JSON do dossiê a partir destes dados:\n' + json.dumps(dados, ensure_ascii=False)}]},
                    timeout=120,
                )
                resp.raise_for_status()
                result = json.loads(resp.json()['choices'][0]['message']['content'])
            for field in ['resumo_executivo', 'capacidade_pagamento', 'patrimonio_garantias', 'parecer_preliminar']:
                st.subheader(field.replace('_', ' ').title())
                st.write(result.get(field, 'Não informado'))
            for field in ['pontos_positivos', 'riscos_pendencias', 'fontes_evidencias']:
                st.subheader(field.replace('_', ' ').title())
                for item in result.get(field, []):
                    st.write('• ' + str(item))
            defesa = str(result.get('defesa_credito', ''))
            st.subheader('Defesa de crédito')
            st.text_area('Versão gerada (revisar)', value=defesa, height=260)
            st.caption(f'{len(defesa)} caracteres. ' + ('ATENÇÃO: excede 2.000 caracteres.' if len(defesa)>2000 else 'Dentro do limite de 2.000.'))
            st.download_button('Baixar dossiê JSON', json.dumps(result, ensure_ascii=False, indent=2), file_name='dossie_credito.json', mime='application/json')
            st.download_button('Baixar defesa TXT', defesa, file_name='defesa_credito.txt', mime='text/plain')
        except Exception as e:
            st.error('Não foi possível concluir. Confira chave, conexão, formato dos documentos e serviço da API.')
            st.code(str(e)[:700])

st.divider()
st.caption('Limitações V1: sem OCR para PDF escaneado, sem validação externa automática Serasa/Bacen, sem consulta cartorial e sem auditoria de extratos transacionais. Os resultados exigem conferência com fontes originais.')
