# ADR 001 — Desenvolvimento em WSL2, com o repositório no sistema de arquivos Linux

- Status: aceito
- Data: 2026-09-02

## Contexto

A máquina de desenvolvimento roda Windows com WSL2 (Ubuntu 26.04). Havia duas
escolhas a fazer, e elas são independentes:

1. **Onde o código roda** — Windows nativo ou dentro do WSL2.
2. **Onde o repositório vive** — no sistema de arquivos do Linux (`~/projetos`)
   ou num disco Windows montado (`/mnt/d/...`).

Dois fatos do projeto restringem a decisão:

**WeasyPrint depende de bibliotecas nativas de GTK.** Ele é usado para gerar os
documentos sintéticos (boletos, informes, extratos) em PDF a partir de templates
Jinja2. WeasyPrint não é Python puro: precisa de Pango, cairo, GDK-PixBuf e
HarfBuzz. No Linux isso é `apt install`. No Windows exige instalar o runtime GTK
por fora do gerenciador de pacotes Python, apontar `WEASYPRINT_DLL_DIRECTORIES`
ou mexer no `PATH`, e conviver com um caminho de instalação que quebra com
frequência. É a fonte de erro mais comum de quem usa WeasyPrint no Windows.

**O restante da stack é nativamente Linux.** Postgres 16 sobe via Docker
Compose, e o alvo mental de deploy de qualquer coisa parecida é um container
Linux. Desenvolver no mesmo sistema operacional em que o código vai rodar elimina
uma classe inteira de diferenças (fim de linha, sensibilidade a maiúsculas no
nome de arquivo, permissões, `os.path` vs `pathlib` em separadores).

Sobre a segunda escolha: o WSL2 acessa discos Windows por meio do 9P, um
protocolo de rede que atravessa a fronteira entre as duas VMs. Toda chamada de
sistema em `/mnt/c` ou `/mnt/d` paga esse custo. Operações que abrem milhares de
arquivos pequenos — que é exatamente o perfil de `uv sync`, de um `import` de
pacote Python, do `pytest` coletando testes e do `mypy` percorrendo o cache —
ficam ordens de grandeza mais lentas. Já `~` no WSL2 é ext4 dentro do disco
virtual da distribuição: I/O local, sem travessia. Além disso, o `/mnt` não
representa permissões nem links simbólicos POSIX com fidelidade, o que confunde
o `.venv` criado pelo uv e o bit de executável dos scripts.

## Decisão

Todo o desenvolvimento acontece dentro do WSL2, e o repositório fica em
`~/projetos/extrator-docs-financeiros` — no ext4 da distribuição, nunca em
`/mnt/c` ou `/mnt/d`.

Decorrem daí:

- Nenhum comando PowerShell ou caminho no estilo `D:\...` entra na documentação,
  nos scripts ou nas instruções do projeto.
- O `.gitattributes` fixa `* text=auto eol=lf`, para que o fim de linha não
  dependa de quem clonou nem de onde.
- As dependências de sistema do WeasyPrint são instaladas via `apt` no Ubuntu do
  WSL2:

  ```bash
  sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
                   libcairo2 libgdk-pixbuf-2.0-0
  ```

- O editor roda no Windows e se conecta ao WSL2 pelo modo remoto (VS Code Remote
  – WSL). A interface é Windows; o processo de linguagem, o terminal, o
  interpretador e os testes são todos Linux.

## Consequências

**Positivas**

- WeasyPrint funciona com uma linha de `apt`, sem runtime GTK avulso nem
  variável de ambiente apontando para DLL.
- `uv sync`, `pytest` e `mypy` rodam em I/O local; a diferença em relação a
  `/mnt` é de segundos para minutos em operações de dependência.
- O ambiente de desenvolvimento é o mesmo tipo de ambiente onde o código
  rodaria em produção, então bugs de plataforma aparecem cedo ou não aparecem.
- Fim de linha e permissões de arquivo ficam consistentes no histórico do git.

**Negativas / custos aceitos**

- O repositório não está visível diretamente no Explorer do Windows por um
  caminho de disco; o acesso é pelo `\\wsl$\Ubuntu\home\marcola\projetos` ou pelo
  editor em modo remoto.
- Backup e sincronização baseados em ferramenta Windows (OneDrive, por exemplo)
  não alcançam a pasta. O backup é o repositório remoto do git.
- O disco virtual do WSL2 (`ext4.vhdx`) cresce e não devolve espaço sozinho ao
  Windows; recuperá-lo exige `wsl --shutdown` e compactação manual, de tempos em
  tempos.
- Ferramentas Windows que precisem ler o projeto pagam agora o custo do 9P na
  direção contrária — é o mesmo pedágio, invertido.

**Não decidido aqui**

- Como o projeto é empacotado ou publicado. A escolha vale para o ambiente de
  desenvolvimento.
