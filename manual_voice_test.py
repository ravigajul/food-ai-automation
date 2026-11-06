# source <project-root>/.venv/bin/activate && python3 <project-root>/manual_voice_test.py
"""
Interactive AI-driven Voice Ordering Test

This script simulates a conversation between an AI customer ("Ravi") and a human
acting as a pizza ordering agent.

Instructions:
1. Run this script: `python manual_voice_test.py`
2. Select the microphone you will use to speak as the agent.
3. The AI customer, "Ravi," will start the conversation.
4. When you see "🔴 Listening for Agent...", speak your response as the
   the voice ordering agent.
5. The script will transc
ribe your response, and Ravi will reply.
6. The conversation continues until the order is complete or someone says "exit".
"""

import argparse
import os
import speech_recognition as sr
import sys
from datetime import datetime
from src.ollama_client import OllamaClient
from src.voice_ai import speak_sync

PERSONAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "personas")


def load_persona(persona_name):
    """Load a persona from a text file in the personas/ directory."""
    filepath = os.path.join(PERSONAS_DIR, f"{persona_name}.txt")
    if not os.path.isfile(filepath):
        available = [
            os.path.splitext(f)[0]
            for f in os.listdir(PERSONAS_DIR)
            if f.endswith(".txt")
        ]
        print(f"❌ Persona '{persona_name}' not found at {filepath}")
        print(f"   Available personas: {', '.join(sorted(available))}")
        sys.exit(1)
    with open(filepath, "r") as f:
        return f.read()


def list_personas():
    """List all available persona files."""
    if not os.path.isdir(PERSONAS_DIR):
        return []
    return sorted(
        os.path.splitext(f)[0] for f in os.listdir(PERSONAS_DIR) if f.endswith(".txt")
    )


PERSONA_GENERATOR_SYSTEM = """You are a test scenario designer for a pizza ordering voice AI system.
Given a user's test scenario description, generate a detailed customer persona prompt.
The persona is always named "Ravi" and is calling a pizza ordering service to order pizza.

You MUST output ONLY the persona prompt text — no commentary, no markdown fences, no preamble.

Follow this exact structure:
1. Opening line describing who Ravi is and the scenario context
2. **Your Order:** — the specific items Ravi wants to order
3. **Conversation Flow:** — numbered steps for Greeting, Ordering, Time Confirmation, Order Review, Final Confirmation, and Handoff
4. **Personality:** — bullet points describing how Ravi behaves
5. **Rules:** — output rules (spoken dialogue only, concise, etc.)
6. **Example Responses:** — 4-6 short example lines Ravi might say"""


def generate_persona_from_scenario(scenario, ollama):
    """Use Ollama to generate a persona prompt from a free-text scenario description."""
    example_persona = load_persona("default")

    prompt = f"""Here is an example persona for reference:

---
{example_persona}
---

Now generate a NEW persona for this test scenario:
"{scenario}"

Output only the persona text, matching the structure of the example above."""

    print("🧠 Generating persona from scenario description...")
    try:
        persona = ollama.generate(prompt, system=PERSONA_GENERATOR_SYSTEM)
        if not persona:
            print(
                "❌ Failed to generate persona from scenario (Ollama returned empty). Falling back to default."
            )
            return load_persona("default")
        return persona
    except Exception as e:
        print(f"❌ An error occurred during persona generation: {e}")
        print("   Falling back to default persona.")
        return load_persona("default")


def select_microphone():
    """Lists available microphones and prompts the user to select one."""
    mics = sr.Microphone.list_microphone_names()
    if not mics:
        print("❌ No microphones found. Please ensure a microphone is connected.")
        sys.exit(1)

    print("🎤 Available Microphones:")
    for i, name in enumerate(mics):
        print(f"   {i}: {name}")

    while True:
        try:
            mic_index = int(
                input(
                    "\nSelect the microphone for the AGENT's voice (enter the number): "
                )
            )
            if 0 <= mic_index < len(mics):
                print(f"✅ Using microphone: {mics[mic_index]}\n")
                return mic_index
            else:
                print("Invalid number. Please try again.")
        except (ValueError, IndexError):
            print("Invalid input. Please enter a number from the list.")


def main():
    """Main function to run the interactive voice ordering session."""
    parser = argparse.ArgumentParser(
        description="Interactive AI-driven Voice Ordering Test"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--persona",
        "-p",
        default=None,
        help=f"Persona file to use. Available: {', '.join(list_personas()) or 'none found'}",
    )
    group.add_argument(
        "--scenario",
        "-s",
        default=None,
        help='Describe a test scenario in plain English, e.g. "customer who is hard of hearing and keeps asking the agent to repeat"',
    )
    parser.add_argument(
        "--list-personas",
        action="store_true",
        help="List available personas and exit",
    )
    parser.add_argument(
        "--mic",
        default="MacBook Pro Microphone",
        help="The default microphone name to search for.",
    )
    args = parser.parse_args()

    if args.list_personas:
        print("Available personas:")
        for name in list_personas():
            print(f"  - {name}")
        return

    ollama = OllamaClient()

    if args.scenario:
        ravi_persona = generate_persona_from_scenario(args.scenario, ollama)
        print(f'📋 Generated persona from scenario: "{args.scenario}"')
        print("-" * 60)
        print(ravi_persona)
        print("-" * 60)
    else:
        persona_name = args.persona or "default"
        ravi_persona = load_persona(persona_name)
        print(f"📋 Loaded persona: {persona_name}")

    # --- Log file setup ---
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_filename = f"test_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    log_filepath = os.path.join(logs_dir, log_filename)
    print(f"📝 Saving conversation log to: {log_filepath}")

    mic_index = None
    try:
        # Try to find and set the default microphone
        mics = sr.Microphone.list_microphone_names()
        default_mic_name = args.mic

        for i, name in enumerate(mics):
            if default_mic_name in name:
                mic_index = i
                print(f"✅ Default microphone found: {name}\n")
                break

        # If default not found, ask the user
        if mic_index is None:
            print("⚠️  Default microphone not found.")
            mic_index = select_microphone()

        recognizer = sr.Recognizer()

        print("You are the Voice Ordering Agent. Speak your opening line.")
        print("-" * 60)

        conversation_history = []
        turn = 1

        with open(log_filepath, "w") as log_file:
            log_file.write(f"Persona: {args.persona or args.scenario or 'default'}\n")
            log_file.write(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_file.write("-" * 20 + "\n\n")

            while True:
                print(f"--- Turn {turn} ---")

                try:
                    # 1. Listen for the Agent's (Human) response
                    with sr.Microphone(device_index=mic_index) as source:
                        recognizer.dynamic_energy_threshold = True
                        recognizer.pause_threshold = 1.2  # Give human some time to pause

                        print("\n   🔴 Listening for Agent...")
                        audio = recognizer.listen(
                            source, timeout=45, phrase_time_limit=30
                        )

                    print("   🔄 Transcribing agent's speech...")
                    agent_speech = recognizer.recognize_whisper(audio, model="tiny.en")
                    print(f'   👨‍💼 Agent (You): "{agent_speech}"')

                    agent_line = f"Agent: {agent_speech}"
                    conversation_history.append(agent_line)
                    log_file.write(agent_line + "\n")

                    if (
                        "exit" in agent_speech.lower()
                        or "goodbye" in agent_speech.lower()
                    ):
                        print("\n🛑 Agent ended the session.")
                        break

                    # Check for termination condition based on agent's speech
                    agent_lower = agent_speech.lower()
                    if any(
                        keyword in agent_lower for keyword in ["transfer", "payment"]
                    ):
                        print(
                            "\n✅ Agent initiated payment transfer. Ending conversation."
                        )
                        # Also get Ravi's final "Thank you"
                        speak_sync("Thank you.")
                        log_file.write("Ravi: Thank you.\n")
                        break

                    # 2. Get AI response
                    print("   🤖 Ravi is thinking...")
                    prompt = f"Conversation History:\n" + "\n".join(
                        conversation_history
                    )
                    prompt += "\n\nYou are Ravi. What do you say next?"

                    ravi_response = ollama.generate(prompt, system=ravi_persona)

                    # 3. Ravi (AI) speaks
                    print(f'   👤 Ravi (AI): "{ravi_response}"')
                    speak_sync(ravi_response)

                    ravi_line = f"Ravi: {ravi_response}"
                    conversation_history.append(ravi_line)
                    log_file.write(ravi_line + "\n")

                    # 4. Check if Ravi is ending the conversation
                    end_phrases = ["goodbye", "thanks, bye"]
                    if any(phrase in ravi_response.lower() for phrase in end_phrases):
                        print("\n✅ Ravi has ended the conversation. Test complete.")
                        break

                except sr.UnknownValueError:
                    print("   ⚠️  Could not understand audio. Please try again.")
                    log_file.write("[Audio not understood]\n")
                    continue
                except sr.RequestError as e:
                    print(f"   Could not request results; {e}")
                    log_file.write(f"[Request Error: {e}]\n")
                    continue

                turn += 1
                print("-" * 60)

    except KeyboardInterrupt:
        print("\n🛑 Session interrupted by user. Exiting.")
    except Exception as e:
        print(f"\n❌ A critical error occurred: {e}")


if __name__ == "__main__":
    main()
