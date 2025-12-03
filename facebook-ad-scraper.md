Com base na sua solicitação, apresento uma explicação completa do fluxo de trabalho da **Ferramenta de Espionagem de Anúncios do Facebook com IA** (AI Facebook Ad Spy Tool), construída integralmente na plataforma N8N, detalhando sua estrutura, passos, finalidade, entradas e saídas esperadas, como se fosse um Procedimento Operacional Padrão (POP/SOP).

***

### 1. Finalidade e Utilidade do Fluxo (Purpose and Utility)

A finalidade deste sistema é fornecer uma solução de alta qualidade para **agências de PPC, empresas de marketing digital** e qualquer entidade que utilize anúncios do Facebook, permitindo que **espionem seus concorrentes** e vejam o que eles estão fazendo.

O sistema serve para:

1.  **Obter Dados de Inteligência Competitiva:** Ao analisar anúncios ativos de concorrentes, o sistema coleta dados abrangentes sobre suas campanhas.
2.  **Geração de Ideias e Repropósito (Repurposing):** Serve como uma fonte de ideias e permite a rápida iteração. Ele facilita a criação de um fluxo de "parasitagem" (`parasite flow`) ou adaptação de campanhas de sucesso em larga escala.
3.  **Criação de Ativos Prontos para IA:** O sistema não apenas resume os anúncios, mas também gera versões reescritas da cópia do anúncio e *prompts* detalhados prontos para serem usados em modelos de texto (como GPT-4.5), imagem (como GPT Image 1) e até mesmo vídeo (como V3).

### 2. Entrada Inicial Necessária (Initial Input)

O fluxo é iniciado com uma entrada de dados simples, mas crucial:

*   **Termo de Busca:** O usuário insere um termo de busca no nó inicial do N8N (desencadeador manual). Este termo é o que será usado para consultar a Biblioteca de Anúncios do Facebook (Facebook Ad Library).
*   **Exemplo:** O construtor usou o termo "AI automation".

### 3. Saída Final Esperada (Final Output)

O resultado final do fluxo é um conjunto de dados estruturados e enriquecidos pela IA, armazenados em uma **Planilha Google (Google Sheet)**.

Os dados de saída incluem:

| Campo | Descrição | Origem dos Dados |
| :--- | :--- | :--- |
| **Ad Archive ID** / **Page ID** | Identificadores únicos do anúncio e da página. | Dados raspados (Appify). |
| **Type** | O tipo de anúncio analisado: `text`, `image` (imagem) ou `video` (vídeo). | Roteamento/Categorização. |
| **Date Added** | Data em que o registro foi adicionado ao banco de dados. | Data atual (expressão `now`). |
| **Page Name** / **Page URL** | Nome e URL do perfil da página do anunciante. | Dados raspados (Appify). |
| **Summary** | Um resumo **extremamente abrangente e analítico** do anúncio, detalhando o que o anúncio está fazendo, como funciona e qual poderia ser a ideia por trás dele. | Gerado por IA (OpenAI/GPT). |
| **Rewritten Ad Copy** | Uma versão reescrita ou adaptada da cópia do anúncio original para fins de *repurposing* ou *parasitagem*. | Gerado por IA (OpenAI/GPT). |
| **Image Prompt** | Um *prompt* detalhado da imagem (se aplicável), gerado pela IA, que pode ser usado para recriar o ativo visual em modelos de imagem (como o GPT Image). | Gerado por IA (OpenAI/GPT). |
| **Video Prompt** | Um *prompt* detalhado do vídeo (se aplicável), gerado pela IA (Gemini e OpenAI), que pode ser usado para recriar o ativo de vídeo em modelos como o V3. | Gerado por IA (Gemini/OpenAI). |

### 4. Estrutura e Fluxo de Trabalho (Estrutura do N8N)

O fluxo é construído no N8N e utiliza uma série de nós conectados que criam três caminhos paralelos para processar diferentes tipos de anúncios.

#### Passo 1: Início e Raspagem de Dados (Scraping and Data Acquisition)

| Ação | Ferramenta/Nó | Detalhes |
| :--- | :--- | :--- |
| **Acionador Manual** | Manual Trigger | Inicia o fluxo. |
| **Executar Ator** | Run Ad Library Scraper Actor (HTTP Request) | Envia o termo de busca para um serviço de raspagem, como o **Appify**, usando o *scraper* "Facebook Ad Library Scraper". Este ator retorna uma lista gigante de anúncios (incluindo texto, imagem/vídeo, e dados da página). O custo do Appify é de cerca de 75 centavos por 1.000 anúncios raspados. |

#### Passo 2: Filtragem de Qualidade (Filtering)

| Ação | Ferramenta/Nó | Detalhes |
| :--- | :--- | :--- |
| **Filtrar por Curtidas** | Filter for Likes | Filtra os anúncios com base em critérios de qualidade. O critério usado é a **contagem de curtidas da página** (`page like count` ou `advertiser likes`). Por exemplo, pode-se filtrar por anunciantes com mais de 10.000 ou 100.000 curtidas para garantir que sejam *big dogs* (anunciantes maiores). |

#### Passo 3: Roteamento e Categorização (Switch Node)

| Ação | Ferramenta/Nó | Detalhes |
| :--- | :--- | :--- |
| **Categorizar** | Switch | Divide o fluxo em três rotas, dependendo do tipo de anúncio (vídeo, imagem ou texto). A lógica segue a ordem de restrição (mais específico primeiro) para evitar que um anúncio de vídeo caia na rota de texto. |
| **Rotas:** | **Video, Image, Text** | 1. **Vídeo:** Verifica a existência de um URL de vídeo (`video SD URL`). 2. **Imagem:** Verifica a existência de um URL de imagem original (`original image URL`). 3. **Texto:** Rota de *fallback* (anúncios que não se qualificam como vídeo ou imagem, presumivelmente apenas texto). |

#### Passo 4: Processamento por IA (AI Processing Loops)

As rotas de vídeo, imagem e texto utilizam um nó **Loop over items** para processar cada anúncio sequencialmente, o que facilita a visualização e a depuração, além de lidar melhor com o tempo de inferência variável da IA.

##### A. Rota de Texto (Loop over text)
1.  **OpenAI:** Envia o *JSON string* completo dos dados raspados para o modelo (e.g., GPT-4.1).
2.  **Prompt:** A IA atua como um "robô de análise de propaganda inteligente".
3.  **Resultado:** Gera o `Summary` (Resumo) e a `Rewritten Ad Copy` (Cópia Reescrita) em formato JSON.

##### B. Rota de Imagem (Loop over image ads)
1.  **Analyze Image (OpenAI):** Utiliza um *endpoint* específico do OpenAI (e.g., GPT-4o) para analisar a URL da imagem.
2.  **Resultado da Análise:** A IA descreve a imagem de forma extremamente abrangente.
3.  **Summarize and Output Image Summary (OpenAI):** O texto do anúncio e a descrição da imagem (gerada na etapa anterior) são enviados ao GPT para gerar o Resumo, a Cópia Reescrita e o **Image Prompt**.

##### C. Rota de Vídeo (Loop over video ads)
Esta é a rota mais complexa, devido à necessidade de *upload* e processamento assíncrono do vídeo:

1.  **Download Video (HTTP Request):** Baixa o arquivo de vídeo do URL (SD URL) como dado binário.
2.  **Upload to Drive (Google Drive Node):** O arquivo binário é carregado para o Google Drive para obter metadados (como o tamanho) necessários para o *upload* ao Gemini.
3.  **Begin Gemini Upload Session (HTTP Request):** Inicia a sessão de upload com a API do Gemini.
4.  **Upload Video to Gemini (HTTP Request):** Carrega o arquivo binário para o Gemini, utilizando o tamanho do arquivo obtido no Drive.
5.  **Wait:** Um nó de **espera obrigatório** (e.g., 10-15 segundos com retentativas) é adicionado, pois o Gemini precisa de tempo para que o arquivo saia do estado inativo e se torne processável.
6.  **Analyze Video with Gemini (HTTP Request):** Solicita ao Gemini (o modelo com capacidade de compreensão de vídeo) uma descrição detalhada e exaustiva do vídeo.
7.  **Summarize and Output Video Summary (OpenAI):** O resultado da análise do Gemini é então enviado ao GPT (junto com o texto original do anúncio) para gerar o Resumo, a Cópia Reescrita e o **Video Prompt**.

#### Passo 5: Armazenamento e Finalização

| Ação | Ferramenta/Nó | Detalhes |
| :--- | :--- | :--- |
| **Adicionar à Planilha** | Add as Type Text/Image/Video (Google Sheets) | Após a análise da IA, os dados processados (incluindo o resumo, as cópias reescritas e os *prompts*) são inseridos na Planilha Google designada, concluindo o ciclo para aquele anúncio específico. |

### 5. Como Construir/Configurar (How to Build It)

A construção é realizada inteiramente no N8N. O processo envolve os seguintes requisitos de configuração:

1.  **Configuração de Credenciais de API (API Keys):**
    *   **Appify:** Obter o token de API na página de integrações para configurar a autorização (Bearer Token) nas requisições HTTP para raspagem.
    *   **OpenAI:** Configurar a chave de API na página de chaves de API para os nós de análise de imagem e texto.
    *   **Gemini/Google:** Obter a chave de API do Gemini, necessária para as requisições HTTP na rota de vídeo (análise e *upload*).
    *   **Google Sheets:** Criar novas credenciais e fazer login via Google para permitir que o N8N acesse e grave na planilha.

2.  **Estrutura da Planilha:** O usuário deve criar uma Planilha Google (chamada, por exemplo, "Facebook Ad Library Analyzer DB") e configurar as colunas para receber os dados de saída listados acima (ID, Type, Summary, etc.).

3.  **Documentação (SOP):** Para facilitar a manutenção e venda do sistema, é crucial documentar os nós e as etapas (explicando as variáveis, *prompts* e chaves de API que o usuário final deve ajustar).

***

**Analogia para o entendimento do fluxo:**

Pense neste fluxo como uma **linha de produção altamente automatizada em uma fábrica de espionagem de anúncios**.

1.  **Entrada (Termo de Busca):** Você joga a matéria-prima (o termo de busca) na esteira.
2.  **Estação de Raspagem (Appify):** Um robô de sucata (Appify) corre para a rua e traz um monte de lixo e tesouros (anúncios) de volta.
3.  **Estação de Filtragem:** Um controle de qualidade joga fora tudo o que é de anunciantes muito pequenos (baixo Page Like Count).
4.  **Estação de Triagem (Switch Node):** Uma bifurcação (o nó Switch) separa os produtos: Vídeos vão para a Seção A, Imagens para a Seção B, e Textos para a Seção C.
5.  **Estações de Análise de IA (OpenAI/Gemini):**
    *   Na Seção de Vídeo, há um processo complicado de upload e espera antes que o especialista (Gemini) possa descrever o que está acontecendo.
    *   Em todas as seções, o time de analistas (GPT) recebe o produto e, em vez de apenas resumi-lo, ele já o transforma em um novo produto (o Resumo e a Cópia Reescrita/Prompt) pronto para ser usado.
6.  **Saída (Google Sheet):** Os produtos finais analisados, detalhados e repropostos são embalados em caixas rotuladas (linhas na Planilha Google).