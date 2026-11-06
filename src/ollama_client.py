"""
Ollama Client for AI-powered test generation and evaluation
"""
import requests
import json
from typing import Dict, List, Optional


class OllamaClient:
    """Client for interacting with local Ollama LLM"""
    
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen2.5:7b"):
        self.base_url = base_url
        self.model = model
        self.api_url = f"{base_url}/api/generate"
        
    def is_available(self) -> bool:
        """Check if Ollama server is running"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=2)
            return response.status_code == 200
        except:
            return False
    
    def generate(self, prompt: str, system: Optional[str] = None, stream: bool = False,
                 temperature: float = 0.1, num_predict: int = 80) -> str:
        """Generate response from Ollama"""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
            },
        }

        if system:
            payload["system"] = system
        
        try:
            response = requests.post(self.api_url, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()['response'].strip()
        except Exception as e:
            print(f"⚠️  Ollama generation failed: {e}")
            return ""
    
    def evaluate_response(self, user_input: str, agent_response: str, expected_behavior: str) -> Dict:
        """
        Use AI to evaluate if the voice agent responded appropriately
        
        Returns dict with:
        - passed: bool
        - score: int (0-100)
        - reasoning: str
        """
        prompt = f"""You are evaluating a voice ordering AI agent for a pizza restaurant.

User said: "{user_input}"
Agent responded: "{agent_response}"
Expected behavior: {expected_behavior}

Evaluate the agent's response quality:
1. Did it understand the user's intent?
2. Was the response appropriate and helpful?
3. Did it follow the expected behavior?

Respond in JSON format:
{{
  "passed": true/false,
  "score": 0-100,
  "reasoning": "brief explanation"
}}
"""
        
        system = "You are a QA evaluator for voice AI systems. Be strict but fair."
        
        response = self.generate(prompt, system=system)
        
        # Parse JSON response
        try:
            # Extract JSON from response
            if '{' in response:
                json_start = response.index('{')
                json_end = response.rindex('}') + 1
                json_str = response[json_start:json_end]
                result = json.loads(json_str)
                return result
            else:
                # Fallback if no JSON
                return {
                    "passed": "yes" in response.lower() or "pass" in response.lower(),
                    "score": 50,
                    "reasoning": response
                }
        except:
            return {
                "passed": False,
                "score": 0,
                "reasoning": f"Failed to parse evaluation: {response}"
            }
    
    def evaluate_dialogue_intent(
        self,
        ravi_says: str,
        lou_response: str,
        intent: str,
        anti_intent: str,
    ) -> Dict:
        """
        LLM-as-judge: evaluate whether Ava's response satisfies the behavioral intent
        and avoids the forbidden anti-intent.

        Returns dict with:
          passed           — True only if intent is met AND anti_intent is not violated
          met_required     — Ava did the required thing
          violated_forbidden — Ava did the forbidden thing
          reasoning        — one-sentence explanation
        """
        prompt = f"""Customer asked: "{ravi_says}"
Agent responded: "{lou_response}"

Required behavior (agent MUST do this):
{intent}

Forbidden behavior (agent MUST NOT do this):
{anti_intent}

Evaluate both requirements independently then set passed = met_required AND NOT violated_forbidden.
Respond with JSON only, no other text:
{{
  "met_required": true or false,
  "violated_forbidden": true or false,
  "passed": true or false,
  "reasoning": "one sentence explanation"
}}"""

        system = (
            "You are a strict QA evaluator for a pizza ordering voice AI. "
            "Evaluate the agent's response against the given behavioral requirements. "
            "Respond ONLY with valid JSON — no markdown, no preamble."
        )

        response = self.generate(
            prompt, system=system, temperature=0.0, num_predict=200
        )

        try:
            if "{" in response:
                json_str = response[response.index("{") : response.rindex("}") + 1]
                result = json.loads(json_str)
                # Ensure passed is consistent with the two sub-fields
                result["passed"] = (
                    bool(result.get("met_required", False))
                    and not bool(result.get("violated_forbidden", False))
                )
                return result
        except Exception:
            pass

        # Fallback: can't parse JSON → conservative fail
        return {
            "met_required": False,
            "violated_forbidden": False,
            "passed": False,
            "reasoning": f"Could not parse evaluator output: {response[:200]}",
        }

    def validate_screen_state(self, ui_elements: List[str], expected_screen: str) -> Dict:
        """
        Use AI to validate if the current screen matches expectations
        based on visible UI elements
        """
        prompt = f"""You are validating the UI state of a mobile app.

Visible UI elements: {ui_elements}
Expected screen: {expected_screen}

Does the current screen match the expected state?

Respond in JSON:
{{
  "matches": true/false,
  "confidence": 0-100,
  "reasoning": "brief explanation"
}}
"""
        
        response = self.generate(prompt)
        
        try:
            if '{' in response:
                json_start = response.index('{')
                json_end = response.rindex('}') + 1
                json_str = response[json_start:json_end]
                return json.loads(json_str)
            else:
                return {
                    "matches": "yes" in response.lower(),
                    "confidence": 50,
                    "reasoning": response
                }
        except:
            return {
                "matches": False,
                "confidence": 0,
                "reasoning": f"Failed to parse: {response}"
            }
    
    def generate_test_scenario(self, persona: str, context: str = "") -> Dict:
        """
        Generate a test scenario based on user persona
        
        Personas:
        - distracted_parent: Changes mind frequently
        - impatient_customer: Wants quick service
        - confused_user: Needs help with the interface
        """
        prompt = f"""Generate a realistic pizza ordering test scenario.

Persona: {persona}
Context: {context}

Create a test scenario with:
1. Initial user utterance
2. Expected agent behavior
3. Follow-up interactions (2-3 turns)
4. Success criteria

Respond in JSON:
{{
  "persona": "{persona}",
  "turns": [
    {{"user": "...", "expected_agent_behavior": "..."}},
    ...
  ],
  "success_criteria": ["..."]
}}
"""
        
        response = self.generate(prompt)
        
        try:
            if '{' in response:
                json_start = response.index('{')
                json_end = response.rindex('}') + 1
                json_str = response[json_start:json_end]
                return json.loads(json_str)
            else:
                # Fallback default scenario
                return {
                    "persona": persona,
                    "turns": [
                        {"user": "I want to order a pizza", "expected_agent_behavior": "Greet and ask what type"},
                        {"user": "Large pepperoni", "expected_agent_behavior": "Confirm and add to cart"}
                    ],
                    "success_criteria": ["Pizza added to cart", "User feels heard"]
                }
        except:
            return {
                "persona": persona,
                "turns": [],
                "success_criteria": []
            }


if __name__ == "__main__":
    # Test the client
    client = OllamaClient()
    
    print("Testing Ollama client...")
    print(f"Ollama available: {client.is_available()}")
    
    if client.is_available():
        # Test evaluation
        result = client.evaluate_response(
            user_input="I want a large pepperoni pizza",
            agent_response="Great! I've added a large pepperoni pizza to your cart. Would you like anything else?",
            expected_behavior="Acknowledge the order and add to cart"
        )
        print(f"\nEvaluation result: {result}")
        
        # Test scenario generation
        scenario = client.generate_test_scenario("distracted_parent")
        print(f"\nGenerated scenario: {json.dumps(scenario, indent=2)}")
