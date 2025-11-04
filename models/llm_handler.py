import os
from openai import OpenAI
from groq import Groq
import subprocess
import json

class LLMHandler:
    def __init__(self):
        self.mode = os.getenv('LLM_MODE', 'local')
        
        # Initialize based on mode
        if self.mode == 'groq':
            self.groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))
            self.model = os.getenv('GROQ_MODEL', 'llama3-8b-8192')
        elif self.mode == 'openai':
            self.openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
            self.model = os.getenv('OPENAI_MODEL', 'gpt-3.5-turbo')
        else:  # local
            self.model = os.getenv('LOCAL_MODEL', 'llama3.2:3b')
    
    def generate(self, prompt, context="", max_tokens=500):
        """
        Generate response based on configured mode
        """
        full_prompt = f"{context}\n\n{prompt}" if context else prompt
        
        try:
            if self.mode == 'local':
                return self._generate_local(full_prompt)
            elif self.mode == 'groq':
                return self._generate_groq(full_prompt, max_tokens)
            elif self.mode == 'openai':
                return self._generate_openai(full_prompt, max_tokens)
        except Exception as e:
            return f"Error generating response: {str(e)}"
    
    def _generate_local(self, prompt):
        """Use Ollama for local generation"""
        try:
            result = subprocess.run(
                ['ollama', 'run', self.model, prompt],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                return f"Error: {result.stderr}"
        except subprocess.TimeoutExpired:
            return "Error: Request timed out. Try a shorter prompt or faster model."
        except FileNotFoundError:
            return "Error: Ollama not installed. Please install from https://ollama.com"
        except Exception as e:
            return f"Error with local model: {str(e)}"
    
    def _generate_groq(self, prompt, max_tokens):
        """Use Groq API (Fast & Free)"""
        response = self.groq_client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system", 
                    "content": "You are a helpful AI assistant that provides accurate, well-researched answers with proper citations from search results."
                },
                {"role": "user", "content": prompt}
            ],
            max_tokens=max_tokens,
            temperature=0.5
        )
        return response.choices[0].message.content
    
    def _generate_openai(self, prompt, max_tokens):
        """Use OpenAI API"""
        response = self.openai_client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system", 
                    "content": "You are a helpful AI assistant that provides accurate, well-researched answers with proper citations from search results."
                },
                {"role": "user", "content": prompt}
            ],
            max_tokens=max_tokens,
            temperature=0.5
        )
        return response.choices[0].message.content
    
    def get_model_info(self):
        """Return current model information"""
        return {
            'mode': self.mode,
            'model': self.model,
            'backend': self.mode.upper()
        }