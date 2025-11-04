from duckduckgo_search import DDGS
import requests
import os

class WebSearch:
    def __init__(self):
        self.serper_key = os.getenv('SERPER_API_KEY')
    
    def search(self, query, max_results=5):
        """
        Search using Serper API with DuckDuckGo fallback
        """
        # Try Serper first if API key is available
        if self.serper_key:
            try:
                results = self._search_serper(query, max_results)
                if results:
                    print(f"✅ Serper API used for: {query}")
                    return results
            except Exception as e:
                print(f"⚠️ Serper failed, using DuckDuckGo fallback: {e}")
        
        # Fallback to DuckDuckGo
        print(f"🦆 DuckDuckGo used for: {query}")
        return self._search_duckduckgo(query, max_results)
    
    def _search_serper(self, query, max_results):
        """
        Search using Serper API (Google results)
        """
        url = "https://google.serper.dev/search"
        headers = {
            'X-API-KEY': self.serper_key,
            'Content-Type': 'application/json'
        }
        payload = {
            'q': query,
            'num': max_results
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        results = []
        
        # Extract organic results
        for r in data.get('organic', [])[:max_results]:
            results.append({
                'title': r.get('title', ''),
                'snippet': r.get('snippet', ''),
                'url': r.get('link', ''),
                'source': 'Google (via Serper)'
            })
        
        # Also check knowledge graph if available
        if 'knowledgeGraph' in data and len(results) < max_results:
            kg = data['knowledgeGraph']
            if 'description' in kg:
                results.insert(0, {
                    'title': kg.get('title', ''),
                    'snippet': kg.get('description', ''),
                    'url': kg.get('website', ''),
                    'source': 'Knowledge Graph'
                })
        
        return results
    
    def _search_duckduckgo(self, query, max_results):
        """
        Free search using DuckDuckGo (no API key needed)
        """
        try:
            ddgs_results = DDGS().text(query, max_results=max_results)
            
            return [
                {
                    'title': r['title'],
                    'snippet': r['body'],
                    'url': r['href'],
                    'source': 'DuckDuckGo'
                }
                for r in ddgs_results
            ]
        except Exception as e:
            print(f"❌ DuckDuckGo search failed: {e}")
            return []
    
    def get_search_stats(self):
        """
        Return which search backend is active
        """
        if self.serper_key:
            return {
                'primary': 'Serper API (Google)',
                'fallback': 'DuckDuckGo',
                'status': 'Active'
            }
        else:
            return {
                'primary': 'DuckDuckGo',
                'fallback': 'None',
                'status': 'Active (Free)'
            }