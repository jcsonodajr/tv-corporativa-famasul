DIGITAL SIGNAGE FAMASUL / SENAR-MS

Arquivos:
- scraper.py: coleta portal FAMASUL, cotações e cursos municipais SENAR-MS.
- .github/workflows/atualizar_tv.yml: execução horária e commit automático de dados_tv.json.
- index.html: interface Full HD, atualização sem F5, clima Open-Meteo.

Configuração:
1. Publique os arquivos em um repositório GitHub.
2. Em Settings > Actions > General, habilite permissões de leitura e escrita para workflows.
3. Execute Actions > Atualizar dados da TV Corporativa > Run workflow uma vez.
4. Publique o repositório via GitHub Pages (Settings > Pages) ou sirva a pasta em um servidor HTTP.
5. Abra index.html?sindicato=dourados (substitua pelo slug do município).
6. Não abra por file://; fetch de JSON local é bloqueado em muitos navegadores. Use localhost/servidor web.
7. Instale dependências localmente com: pip install requests beautifulsoup4

LIMITAÇÕES QUE EXIGEM VALIDAÇÃO ANTES DE USO INSTITUCIONAL:
- Os seletores dos portais podem mudar; confirme os dados coletados no JSON antes de pôr em produção.
- O portal SENAR-MS pode carregar parte dos cursos por JavaScript, caso em que requests/BeautifulSoup não vê o conteúdo renderizado; se isso ocorrer, será necessário usar Playwright ou localizar o endpoint JSON/XHR do portal.
- As regiões de pecuária e a herança de praças são regras iniciais configuráveis no scraper.py. Valide-as com a metodologia oficial vigente do Sistema FAMASUL.
- O painel não inventa variações percentuais: mostra “n/d” porque o scraper coleta cotações atuais/históricas, mas ainda não calcula comparação de dias úteis com validação de datas e praça.
- O geocoding do Open-Meteo resolve o município em tempo de execução. Isso evita coordenadas aproximadas fixas e não exige cadastrar 79 pares manualmente.
- Não há proxy CORS no frontend: os proxies públicos não são uma base de produção confiável. A TV deve consumir dados_tv.json servido no mesmo domínio.
