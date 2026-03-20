import guava

if __name__ == "__main__":
    sip_code = guava.Client().create_sip_agent()
    print("Created a new agent with SIP code:", sip_code)
