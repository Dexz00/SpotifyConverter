<div align="center">

# 🎵 SpotifyConverter

**Converta links do Spotify (faixa, álbum ou playlist) em `.mp3`** — com qualidade
até 320 kbps, capa do álbum e tags ID3, por uma interface web bonita e **sem cadastro**.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![yt-dlp](https://img.shields.io/badge/yt--dlp-FF0000?logo=youtube&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

</div>

> Inspirado em sites como o spotidownloader.com, mas com **qualidade configurável**,
> **playlists/álbuns inteiros**, download em **`.zip`**, tags embutidas e — o pulo do
> gato — **seleção inteligente da versão de áudio certa** (nada de pegar o videoclipe).

---

## ✨ Recursos

- 🔗 Faixa, **álbum** ou **playlist** — cola o link e pronto
- 🎚️ Qualidade selecionável: **128 / 192 / 256 / 320 kbps**
- 🖼️ **Capa do álbum + tags ID3** (título, artista, álbum) embutidas no MP3
- 🧠 **Escolhe a faixa de áudio certa** no YouTube por duração + tipo de canal
  (evita videoclipe, versão ao vivo, remix, loops…)
- 📦 Botão **"Baixar tudo (.zip)"** para coleções
- 📡 Progresso em **tempo real** (Server-Sent Events)
- 🔌 Funciona **sem cadastro**; opcionalmente usa a **API oficial do Spotify**
  para playlists/álbuns completos e metadados mais ricos

---

## ⚙️ Como funciona

O Spotify entrega o áudio com **DRM**, então nenhuma ferramenta baixa o arquivo
"de dentro" do Spotify. O fluxo (o mesmo de todos esses sites) é:

```
         ┌─ metadados (nome, artista, álbum, capa) ──► do SPOTIFY
Link  ───┤
         └─ áudio (o .mp3 em si) ───────────────────► do YOUTUBE (yt-dlp)
                                                         └─ convertido p/ MP3 + tags (ffmpeg + mutagen)
```

A diferença deste projeto: em vez de pegar o primeiro resultado do YouTube (que
costuma ser o videoclipe), ele **busca vários candidatos e escolhe o melhor**
comparando a duração com a do Spotify e priorizando canais de áudio oficiais.

---

## 🚀 Começando

### Windows (mais fácil)

Dê dois cliques em **`run.bat`**. Ele cria o ambiente, instala as dependências,
baixa o `ffmpeg` e abre o navegador.

### Manual (qualquer SO)

```bash
git clone https://github.com/Dexz00/SpotifyConverter.git
cd SpotifyConverter

python -m venv .venv
# Windows:   .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate

pip install -r requirements.txt
python setup_ffmpeg.py        # baixa o ffmpeg p/ ./bin (Windows); no Linux/Mac use o gerenciador de pacotes
python run.py
```

Abra **http://127.0.0.1:8000**, cole o link e clique em **Converter**.
Os arquivos ficam em `downloads/<id-do-job>/`.

---

## 🔑 (Opcional) API oficial do Spotify

Funciona sem nada disso. Mas com credenciais você ganha **playlists/álbuns
inteiros** (paginados) e metadados mais ricos. Um selinho na home mostra o modo ativo.

1. Em https://developer.spotify.com/dashboard, **Create app** (Redirect URI pode ser `http://127.0.0.1:8000`)
2. Copie o **Client ID** e o **Client Secret** em *Settings*
3. Copie `.env.example` para `.env` e preencha:

   ```env
   SPOTIFY_CLIENT_ID=seu_client_id
   SPOTIFY_CLIENT_SECRET=seu_client_secret
   ```

4. Rode de novo. Se as credenciais falharem, ele volta sozinho ao modo sem cadastro.

> ⚠️ O `.env` está no `.gitignore` — suas credenciais **nunca** vão pro GitHub.

---

## 🗂️ Estrutura

```
SpotifyConverter/
├── app/
│   ├── spotify.py       # metadados sem API (página de embed)
│   ├── spotify_api.py   # metadados via API oficial (opcional)
│   ├── resolver.py      # escolhe a melhor fonte de metadados
│   ├── downloader.py    # busca + seleção + yt-dlp + ffmpeg + tags/capa
│   └── main.py          # API FastAPI + progresso SSE + serve o frontend
├── web/                 # frontend (HTML / CSS / JS puro, sem build)
├── setup_ffmpeg.py      # baixa o ffmpeg automaticamente
├── run.py               # entrypoint do servidor
├── run.bat              # launcher 1-clique (Windows)
└── requirements.txt
```

---

## 🛠️ Usando como base (pro próximo dev)

- **Trocar a fonte de áudio?** Mexa só em `app/downloader.py` — `_pick_best`/
  `_score_candidate` decidem qual resultado baixar; `download_track` faz o resto.
- **Outro formato (m4a, flac, opus)?** Ajuste o `FFmpegExtractAudio` em `download_track`.
- **Novos metadados?** `app/resolver.py` é o ponto único; ele cai do oficial pro embed.
- **Frontend** é HTML/CSS/JS puro em `web/` — sem build, sem framework, fácil de editar.

PRs e forks são bem-vindos. 🙂

---

## ⚖️ Aviso legal

Ferramenta para **uso pessoal e educativo**. Baixar conteúdo protegido por
direitos autorais pode violar os termos do Spotify/YouTube e a lei do seu país.
Use apenas com material que você tem o direito de baixar.

---

## 📄 Licença

[MIT](LICENSE) © [Dexz00](https://github.com/Dexz00)
