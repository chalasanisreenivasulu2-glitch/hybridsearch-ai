from flask import Flask, render_template, request, jsonify, session, send_from_directory
import secrets
import requests
from groq import Groq
from openai import OpenAI
import json
from datetime import datetime, timedelta
from functools import wraps
import time
import os
from dotenv import load_dotenv
from collections import defaultdict

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(16))

# Configuration
CACHE_DURATION = int(os.getenv('CACHE_DURATION', 3600))  # 1 hour default
MAX_HISTORY = int(os.getenv('MAX_HISTORY', 10))  # Maximum number of searches

# Rate limiting configuration
RATE_LIMIT_SEARCHES = 50  # searches per hour
RATE_LIMIT_WINDOW = 3600  # 1 hour in seconds

# In-memory cache, history, and rate limiting
search_cache = {}
search_history = []
rate_limit_tracker = defaultdict(list)  # {user_id: [timestamp1, timestamp2, ...]}

# API Configuration - Load from environment variables
API_KEYS = {
    'serper': os.getenv('SERPER_API_KEY'),
    'groq': os.getenv('GROQ_API_KEY'),
    'openai': os.getenv('OPENAI_API_KEY')  # Optional
}

# Validate required API keys
def validate_api_keys():
    """Check if required API keys are configured"""
    missing_keys = []
    
    if not API_KEYS['serper']:
        missing_keys.append('SERPER_API_KEY')
    if not API_KEYS['groq']:
        missing_keys.append('GROQ_API_KEY')
    
    if missing_keys:
        print("\n" + "="*50)
        print("⚠️  WARNING: Missing API Keys!")
        print("="*50)
        for key in missing_keys:
            print(f"   - {key}")
        print("\nPlease create a .env file with your API keys.")
        print("See .env.example for the template.")
        print("="*50 + "\n")
        return False
    return True

# Model configurations - Load from environment or use defaults
MODEL_CONFIGS = {
    'groq': {
        'backend': 'Groq API',
        'model': os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile'),
        'display_name': os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile').replace('-versatile', '')
    },
    'openai': {
        'backend': 'OpenAI',
        'model': os.getenv('OPENAI_MODEL', 'gpt-4o-mini'),
        'display_name': os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
    },
    'local': {
        'backend': 'Ollama',
        'model': os.getenv('LOCAL_MODEL', 'llama2'),
        'display_name': os.getenv('LOCAL_MODEL', 'llama2')
    }
}

# ========== RATE LIMITING ==========

def get_user_id():
    """Get or create unique user ID"""
    if 'user_id' not in session:
        session['user_id'] = secrets.token_hex(16)
    return session['user_id']

def check_rate_limit(user_id):
    """Check if user has exceeded rate limit"""
    now = time.time()
    
    # Clean old timestamps
    rate_limit_tracker[user_id] = [
        ts for ts in rate_limit_tracker[user_id]
        if now - ts < RATE_LIMIT_WINDOW
    ]
    
    # Check limit
    if len(rate_limit_tracker[user_id]) >= RATE_LIMIT_SEARCHES:
        return False, 0
    
    return True, RATE_LIMIT_SEARCHES - len(rate_limit_tracker[user_id])

def record_search(user_id):
    """Record a search for rate limiting"""
    rate_limit_tracker[user_id].append(time.time())

def rate_limit_decorator(func):
    """Decorator to enforce rate limiting"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        user_id = get_user_id()
        allowed, remaining = check_rate_limit(user_id)
        
        if not allowed:
            return render_template('error.html', 
                                 error='Rate limit exceeded. Please try again in an hour.'), 429
        
        record_search(user_id)
        return func(*args, **kwargs)
    return wrapper

# ========== CACHE DECORATOR ==========
def cache_result(duration=CACHE_DURATION):
    """Decorator to cache function results"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key from function name and arguments
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Check if result is in cache and not expired
            if cache_key in search_cache:
                cached_data, timestamp = search_cache[cache_key]
                if time.time() - timestamp < duration:
                    print(f"Cache hit for: {cache_key[:50]}...")
                    return cached_data
            
            # Call function and cache result
            result = func(*args, **kwargs)
            search_cache[cache_key] = (result, time.time())
            return result
        return wrapper
    return decorator

# ========== HELPER FUNCTIONS ==========

@cache_result(duration=3600)
def search_web(query):
    """Search the web using Serper API with caching"""
    if not API_KEYS['serper']:
        return [{
            'title': 'API Key Not Configured',
            'snippet': 'Please add SERPER_API_KEY to your .env file. Get one at https://serper.dev',
            'url': 'https://serper.dev',
            'source': 'Error'
        }]
    
    url = "https://google.serper.dev/search"
    headers = {
        'X-API-KEY': API_KEYS['serper'],
        'Content-Type': 'application/json'
    }
    payload = {'q': query, 'num': 5}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        results = response.json()
        
        sources = []
        for item in results.get('organic', [])[:5]:
            sources.append({
                'title': item.get('title', 'No title'),
                'snippet': item.get('snippet', 'No description available'),
                'url': item.get('link', '#'),
                'source': 'Serper'
            })
        
        if not sources:
            sources.append({
                'title': 'No Results Found',
                'snippet': 'Try a different search query.',
                'url': '#',
                'source': 'Serper'
            })
        
        return sources
    
    except requests.exceptions.Timeout:
        return [{
            'title': 'Search Timeout',
            'snippet': 'The search request took too long. Please try again.',
            'url': '#',
            'source': 'Error'
        }]
    except requests.exceptions.RequestException as e:
        print(f"Search error: {e}")
        return [{
            'title': 'Search Error',
            'snippet': f'Unable to perform search: {str(e)}',
            'url': '#',
            'source': 'Error'
        }]

def generate_answer_groq(query, sources):
    """Generate AI answer using Groq"""
    if not API_KEYS['groq']:
        return "Error: Groq API key not configured. Please add GROQ_API_KEY to your .env file."
    
    try:
        client = Groq(api_key=API_KEYS['groq'])
        
        context = "\n\n".join([f"**{s['title']}**: {s['snippet']}" for s in sources if s['source'] != 'Error'])
        
        prompt = f"""You are a helpful AI assistant. Based on the following sources, provide a comprehensive and well-structured answer to this question: {query}

Sources:
{context}

Instructions:
- Provide a detailed, informative answer
- Use bullet points and clear structure
- Cite information naturally
- If sources are insufficient, acknowledge limitations
- Be accurate and objective

Answer:"""
        
        response = client.chat.completions.create(
            model=MODEL_CONFIGS['groq']['model'],
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2000
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        print(f"Groq error: {e}")
        return f"Error generating answer with Groq: {str(e)}\n\nPlease check your API key or try a different model."

def generate_answer_openai(query, sources):
    """Generate AI answer using OpenAI"""
    if not API_KEYS['openai']:
        return "Error: OpenAI API key not configured. Please add OPENAI_API_KEY to your .env file."
    
    try:
        client = OpenAI(api_key=API_KEYS['openai'])
        
        context = "\n\n".join([f"**{s['title']}**: {s['snippet']}" for s in sources if s['source'] != 'Error'])
        
        prompt = f"""You are a helpful AI assistant. Based on the following sources, provide a comprehensive and well-structured answer to this question: {query}

Sources:
{context}

Instructions:
- Provide a detailed, informative answer
- Use bullet points and clear structure
- Cite information naturally
- If sources are insufficient, acknowledge limitations
- Be accurate and objective

Answer:"""
        
        response = client.chat.completions.create(
            model=MODEL_CONFIGS['openai']['model'],
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2000
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        print(f"OpenAI error: {e}")
        return f"Error generating answer with OpenAI: {str(e)}\n\nPlease check your API key or try a different model."

def generate_answer_local(query, sources):
    """Generate AI answer using Ollama (local)"""
    try:
        context = "\n\n".join([f"**{s['title']}**: {s['snippet']}" for s in sources if s['source'] != 'Error'])
        
        prompt = f"""Based on the following sources, answer this question: {query}

Sources:
{context}

Provide a comprehensive answer:"""
        
        # Get model from config
        local_model = MODEL_CONFIGS['local']['model']
        
        response = requests.post(
            'http://localhost:11434/api/generate',
            json={
                'model': local_model,
                'prompt': prompt,
                'stream': False
            },
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json().get('response', 'No response generated')
        else:
            return f"Error: Ollama returned status code {response.status_code}"
    
    except requests.exceptions.ConnectionError:
        return "Error: Cannot connect to Ollama. Make sure Ollama is running locally (http://localhost:11434)"
    except Exception as e:
        print(f"Local AI error: {e}")
        return f"Error generating answer with Ollama: {str(e)}"

def generate_answer(query, sources, mode='groq'):
    """Generate answer using selected AI backend"""
    if mode == 'openai':
        return generate_answer_openai(query, sources)
    elif mode == 'local':
        return generate_answer_local(query, sources)
    else:  # default to groq
        return generate_answer_groq(query, sources)

def add_to_history(query, mode):
    """Add search to history"""
    global search_history
    
    history_entry = {
        'query': query,
        'mode': mode,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    # Add to beginning of list
    search_history.insert(0, history_entry)
    
    # Keep only last MAX_HISTORY items
    search_history = search_history[:MAX_HISTORY]

def get_current_mode():
    """Get current AI mode from session"""
    return session.get('ai_mode', 'groq')

def get_model_info(mode=None):
    """Get model information for display"""
    if mode is None:
        mode = get_current_mode()
    
    config = MODEL_CONFIGS.get(mode, MODEL_CONFIGS['groq'])
    return {
        'backend': config['backend'],
        'model': config['display_name'],
        'mode': mode,
        'status': 'active'
    }

# ========== ROUTES ==========

@app.route('/')
def index():
    """Home page"""
    model_info = get_model_info()
    
    search_info = {
        'primary': 'Serper API',
        'fallback': 'DuckDuckGo',
        'status': 'Ready'
    }
    
    return render_template('index.html', 
                         model_info=model_info, 
                         search_info=search_info,
                         history=search_history[:5])  # Show last 5 searches

@app.route('/search', methods=['POST'])
@rate_limit_decorator
def search():
    """Handle search requests"""
    query = request.form.get('query', '').strip()
    
    if not query:
        return render_template('error.html', 
                             error='Please enter a search query'), 400
    
    # Get current AI mode
    mode = get_current_mode()
    model_info = get_model_info(mode)
    
    # Get rate limit info
    user_id = get_user_id()
    _, remaining = check_rate_limit(user_id)
    
    try:
        # Search the web (cached)
        sources = search_web(query)
        
        # Generate AI answer
        answer = generate_answer(query, sources, mode)
        
        # Add to history
        add_to_history(query, mode)
        
        return render_template('results.html', 
                             query=query,
                             answer=answer,
                             sources=sources,
                             model_info=model_info,
                             rate_limit_remaining=remaining)
    
    except Exception as e:
        print(f"Search error: {e}")
        return render_template('error.html', 
                             error=f'An error occurred: {str(e)}'), 500

@app.route('/switch_mode', methods=['POST'])
def switch_mode():
    """Switch AI backend mode"""
    mode = request.form.get('mode', 'groq')
    
    if mode not in MODEL_CONFIGS:
        return jsonify({
            'success': False,
            'error': f'Invalid mode: {mode}'
        }), 400
    
    # Save mode to session
    session['ai_mode'] = mode
    
    config = MODEL_CONFIGS[mode]
    
    return jsonify({
        'success': True,
        'mode': mode,
        'backend': config['backend'],
        'model': config['display_name']
    })

@app.route('/history')
def history():
    """Get search history"""
    return jsonify({
        'history': search_history,
        'count': len(search_history)
    })

@app.route('/clear_cache', methods=['POST'])
def clear_cache():
    """Clear search cache"""
    global search_cache
    search_cache.clear()
    return jsonify({
        'success': True,
        'message': 'Cache cleared successfully'
    })

@app.route('/clear_history', methods=['POST'])
def clear_history():
    """Clear search history"""
    global search_history
    search_history.clear()
    return jsonify({
        'success': True,
        'message': 'History cleared successfully'
    })

@app.route('/stats')
def stats():
    """Get application statistics"""
    user_id = get_user_id()
    _, remaining = check_rate_limit(user_id)
    
    return jsonify({
        'cache_size': len(search_cache),
        'history_size': len(search_history),
        'current_mode': get_current_mode(),
        'available_modes': list(MODEL_CONFIGS.keys()),
        'rate_limit_remaining': remaining,
        'rate_limit_max': RATE_LIMIT_SEARCHES
    })

@app.route('/manifest.json')
def manifest():
    """Serve PWA manifest"""
    manifest_data = {
        "name": "HybridSearch AI",
        "short_name": "HybridSearch",
        "description": "AI-powered search engine with multiple backends",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#667eea",
        "theme_color": "#667eea",
        "orientation": "portrait-primary",
        "icons": [
            {
                "src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🔍</text></svg>",
                "sizes": "192x192",
                "type": "image/svg+xml"
            }
        ]
    }
    return jsonify(manifest_data)

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    return send_from_directory('static', filename)

# ========== ERROR HANDLERS ==========

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', 
                         error='Page not found'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', 
                         error='Internal server error'), 500

# ========== MAIN ==========

if __name__ == '__main__':
    print("=" * 50)
    print("HybridSearch AI - Production Server")
    print("=" * 50)
    
    # Validate API keys
    if not validate_api_keys():
        print("⚠️  Starting server with missing API keys...")
        print("    Some features may not work properly.\n")
    else:
        print("✅ All required API keys configured!")
    
    print(f"Cache enabled: {CACHE_DURATION}s duration")
    print(f"History enabled: Max {MAX_HISTORY} searches")
    print(f"Available modes: {', '.join(MODEL_CONFIGS.keys())}")
    print("=" * 50)
    print("\nStarting server at http://127.0.0.1:5000")
    print("Press Ctrl+C to stop\n")
    
    # Check if running in production
    if os.getenv('FLASK_ENV') == 'production':
        app.run(debug=False, host='0.0.0.0', port=5000)
    else:
        app.run(debug=True, host='0.0.0.0', port=5000)