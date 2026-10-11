# GitShare Backend - FastAPI + Supabase

Secure FastAPI backend for the GitShare Chrome extension. Enables sharing private GitHub repositories through temporary, encrypted links.

## How It Works

### Architecture Overview

GitShare uses a **server-side architecture** where the backend acts as a secure proxy between viewers and GitHub:

```
User creates link → Extension → Backend → GitHub OAuth
                                   ↓
                            Encrypt & Store Token
                                   ↓
Viewer opens link → Backend → Decrypt Token → Fetch from GitHub → Render HTML
```

### Smart Link Management

**Duplicate Prevention:**
Before creating a new link, the system checks if a valid link already exists for the same repository and user:

**Benefits:**
- Prevents link proliferation (one link per repo per user)
- Consistent URLs for the same repository
- Reduced database entries
- Simpler link management for users

### Security Model

**Token Lifecycle:**
1. User authenticates via GitHub OAuth (extension handles this)
2. Backend exchanges OAuth code for access token (keeps client secret secure)
3. Token encrypted with Fernet (AES-128) before database storage
4. Token only decrypted server-side when fetching repository data

**Access Control:**
- Links are cryptographically random (22+ characters, URL-safe)
- Each link tied to specific repository + user
- Automatic expiration (1-60 days, user configurable)
- Access tracking (count + last IP + timestamp)
- Only link creator can revoke access

### Repository Viewer

**Lazy Loading Architecture:**
The viewer HTML page loads basic repository information immediately, then fetches additional data on-demand:

- **Initial Load:** Repository info + root directory contents
- **On Tab Click:** Commits, forks, or stargazers fetched via AJAX
- **On Navigation:** Directory contents loaded as user browses
- **File Viewing:** Content fetched only when file is clicked

**Benefits:**
- Fast initial page load
- Reduced GitHub API calls
- Better user experience
- Respects GitHub rate limits


## Prerequisites

- Python 3.9+
- Supabase account
- GitHub OAuth App credentials

## Setup Instructions

### 1. Create Supabase Database Tables

Run these SQL commands in your Supabase SQL Editor:

```sql
create table public.share_links (
  link_id text not null,
  owner text not null,
  repo text not null,
  encrypted_token text not null,
  user_id text not null,
  created_at timestamp with time zone not null default now(),
  expires_at timestamp with time zone not null,
  access_count integer null default 0,
  last_accessed_at timestamp with time zone null,
  last_ip text null,
  constraint share_links_pkey primary key (link_id)
) TABLESPACE pg_default;

create index IF not exists idx_share_links_user_id on public.share_links using btree (user_id) TABLESPACE pg_default;

create index IF not exists idx_share_links_expires_at on public.share_links using btree (expires_at) TABLESPACE pg_default;
```

### 2. Create GitHub OAuth App

1. Go to GitHub Settings → Developer settings → OAuth Apps → New OAuth App
2. Set Authorization callback URL to: `chrome-extension://YOUR_EXTENSION_ID` (get this after building extension)
3. Note down **Client ID** and **Client Secret**

### 3. Install uv and Dependencies

```bash
cd fastapi-supabase-app

# Install uv (ultra-fast Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
# Or on macOS: brew install uv

# Create virtual environment with uv
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies with uv
uv pip install -r requirements.txt
```

### 4. Generate Encryption Key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output - you'll need it for `.env`

### 5. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

```env
# Supabase Configuration (from Supabase Dashboard → Settings → API)
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_KEY=your_anon_key
SUPABASE_SERVICE_KEY=your_service_role_key

# GitHub OAuth (from GitHub OAuth App)
GITHUB_CLIENT_ID=your_github_client_id
GITHUB_CLIENT_SECRET=your_github_client_secret

# Encryption (generated above)
ENCRYPTION_KEY=your_fernet_key

# Backend Configuration
BACKEND_URL=http://localhost:8000

# Environment
ENVIRONMENT=development
DEBUG=True
```

### 6. Run the Server

```bash
# Development mode (with auto-reload)
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Or using Python directly
python -m src.main
```

Server will be available at `http://localhost:8000`

## API Endpoints

### Health & Status
- `GET /` - API information
- `GET /health` - Health check

### Authentication
- `POST /api/github-auth` - Exchange GitHub OAuth code for access token

### Share Link Management
- `POST /api/generate-link` - Generate a new share link for a repository
- `DELETE /api/revoke-link` - Revoke an existing share link

### Repository Viewer
- `GET /view/{link_id}` - View shared repository (returns HTML page)
- `GET /api/view/{link_id}/commits` - Get repository commits
- `GET /api/view/{link_id}/forks` - Get repository forks
- `GET /api/view/{link_id}/stargazers` - Get repository stargazers
- `GET /api/view/{link_id}/contents` - Get directory contents (file browser)
- `GET /api/view/{link_id}/file` - Get text file content
- `GET /api/view/{link_id}/raw` - Get binary file content (images, PDFs)

All viewer endpoints require a valid, non-expired `link_id`. The GitHub access token is stored encrypted and never exposed to the client.

## Security Best Practices

### What We Do

1. **Encryption at Rest**: All GitHub tokens encrypted with Fernet before storage
2. **Server-Side Fetching**: Extension never sees the token, all GitHub API calls from backend
4. **Input Validation**: All inputs validated with Pydantic schemas
5. **CORS Pattern Matching**: Accepts chrome-extension://* and localhost for zero-config setup
6. **OAuth Authentication**: GitHub OAuth required for all operations
7. **Audit Logging**: All actions logged with timestamps and IPs
8. **Automatic Cleanup**: Links expire after user-chosen duration (1-30 days)

### CORS Configuration (Zero-Config for Users)

The backend is configured to accept requests from **any Chrome extension** for easy distribution:

**Accepted Origins:**
- `chrome-extension://[any-id]` - All Chrome extensions
- `http://localhost:[port]` - Local development
- `http://127.0.0.1:[port]` - Local development

**Why This Is Safe:**
- GitHub OAuth authentication required for all operations
- Tokens are encrypted in database
- Each user can only access their own repositories
- Links expire automatically
- Rate limiting prevents abuse
- Tokens never exposed to clients

**User Benefit:**
Users can download your extension ZIP, load it in Chrome, and it works immediately without any CORS configuration. Each user's extension will have a different ID when loaded unpacked, but the backend accepts all of them.

## License

MIT

## Support

For issues or questions, create an issue on GitHub.

## Usage

Once the application is running, you can access the API at `http://localhost:8000`. You can also access the interactive API documentation at `http://localhost:8000/docs`.

## License

This project is licensed under the MIT License.