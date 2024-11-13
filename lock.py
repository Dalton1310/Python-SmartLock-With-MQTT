import paho.mqtt.client as mqtt
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes
import json

# =====================================================================================================================
#                                             Smart Lock (slock) Initialization
# =====================================================================================================================


MQTT_RESPONSE_TOPIC = "lock/update"  # Topic under which slock publishes updates on its state.

# Read slock Configurations
with open("lock.json", "r") as config_file:
    config_options = json.load(config_file)

# Load slock Configurations
slock = mqtt.Client(client_id=config_options["mqtt_client_id"],
                    protocol=mqtt.MQTTv5,
                    transport=config_options["mqtt_transport"])
slock.username_pw_set(username=config_options["mqtt_client_id"],
                      password=config_options["mqtt_perm_pass"])


# =====================================================================================================================
#                                                   Utility Functions
# =====================================================================================================================


def authenticate(config, password):
    """
    Determines whether a password is the permanent password, the temporary password, or neither.
    :param config: configuration for slock which contains slock passwords.
    :param password: password whose status will be checked.
    :returns: status of the password (0=Neither, 1=Permanent, 2=Temporary and Active)
    """
    if config["mqtt_perm_pass"] == password:
        return 1  # Password is Permanent
    if config["mqtt_temp_active"] and config_options["mqtt_temp_pass"] == password:
        return 2  # Password is Temporary and Active
    return 0  # Password is Neither


def publish(config, topic, message):
    """
    Publishes a message to a topic at the qos in the slock configuration.
    :param config: configuration for slock which contains the qos.
    :param topic: topic that will be published under.
    :param message: message that will be published.
    """
    publish_properties = Properties(PacketTypes.PUBLISH)
    publish_properties.MessageExpiryInterval = 30
    slock.publish(topic=topic,
                  payload=message,
                  qos=config["mqtt_qos"],
                  retain=False,
                  properties=publish_properties)


# =====================================================================================================================
#                                                MQTT Topic Callbacks
# =====================================================================================================================


def toggle_lock(self, userdata, message):
    """
    Changes the lock state of slock (i.e. locked or unlocked) based on publisher messages.
    :param self: current slock instance
    :param userdata: private user data as set in Client() or user_data_set()
    :param message: message containing password from publisher
    """
    # Authenticate the password in the message.
    password = message.payload.decode()
    topic = message.topic
    redundant = config_options["locked"] == 0 and topic == "lock/unlock" \
        or config_options["locked"] == 1 and topic == "lock/lock"  # Check if request is redundant.
    authenticated = authenticate(config_options, password)

    response_message = "Failure: Locking Failed" if topic == "lock/lock" else "Failure: Unlocking Failed"

    if authenticated != 0:  # If the password is authenticated, lock or unlock slock.
        if not redundant:  # If locking or unlocking request is not redundant (slock is not already locked or unlocked)
            config_options["locked"] = 0 if config_options["locked"] == 1 else 1  # Toggle the lock state of slock
            if authenticated == 2 and config_options["locked"] == 0:  # if temporary password was used to unlock,
                config_options["mqtt_temp_active"] = 0  # the deactivate temporary password.

        # Dump the changes to the lock state to the slock's configuration file.
        with open("lock.json", "w") as f:
            json.dump(config_options, f)

        # Construct slock state update message
        response_prefix = "Already" if redundant else "Now"
        response_type = "Engaged" if topic == "lock/lock" else "Disengaged"
        response_message = f"Success: Lock {response_prefix} {response_type}"

    publish(config_options, MQTT_RESPONSE_TOPIC, response_message)  # Publish slock state update message


def toggle_temp_password(self, userdata, message):
    """
    Changes the lock state of slock (i.e. locked or unlocked) based on publisher messages.
    :param self: current slock instance
    :param userdata: private user data as set in Client() or user_data_set()
    :param message: message containing password from publisher
    """
    password = message.payload.decode()
    topic = message.topic
    redundant = config_options["mqtt_temp_active"] == 0 and topic == "lock/password/temp/deactivate" \
        or config_options["mqtt_temp_active"] == 1 and topic == "lock/password/temp/activate"  # Check if request is redundant.
    authenticated = authenticate(config_options, password)

    response_message = "Failure: Temp Password Activation Failed" \
        if topic == "lock/password/temp/activate" else "Failure: Temp Password Deactivation Failed"

    if authenticated == 1:  # If password is the permanent password, activate or deactivate the temporary password.
        if not redundant:  # If request is not redundant (temporary password is not already active or inactive).
            config_options["mqtt_temp_active"] = 0 \
                if config_options["mqtt_temp_active"] == 1 else 1  # Toggle the activation state of temporary password.

        # Dump the changes to the temporary password activation state to the slock's configuration file.
        with open("lock.json", "w") as f:
            json.dump(config_options, f)

        # Construct slock state update message
        response_prefix = "Already" if redundant else "Now"
        response_type = "Activated" if topic == "lock/password/temp/activate" else "Deactivated"
        response_message = f"Success: Temp Password {response_prefix} {response_type}"

    publish(config_options, MQTT_RESPONSE_TOPIC, response_message)  # Publish slock state update message


# =====================================================================================================================
#                                                MQTT Broker Connection
# =====================================================================================================================


BROKER_HOST = 'localhost'
BROKER_PORT = 1883
connection_properties = Properties(PacketTypes.CONNECT)
connection_properties.SessionExpiryInterval = 1800
slock.will_set(topic=MQTT_RESPONSE_TOPIC,
               payload=f"ERROR: Connection to Smart Lock {config_options['mqtt_client_id']} Lost",
               qos=config_options["mqtt_qos"],
               retain=True,
               properties=Properties(PacketTypes.WILLMESSAGE))
slock.connect(host=BROKER_HOST,
              port=BROKER_PORT,
              properties=connection_properties,
              keepalive=60)


# =====================================================================================================================
#                                                 MQTT Non-Topic Callbacks
# =====================================================================================================================


def on_connect(client, userdata, flags, reasonCode, properties):
    """
    Callback for new MQTT connection events.
    Subscribes slock to all the following topics:\n
    - lock/lock
    - lock/unlock
    - lock/password/temp/active
    - lock/password/temp/deactivate
    :param client: the client instance for this callback
    :param userdata: the private user data as set in Client() or user_data_set()
    :param flags: response flags sent by the broker
    :param reasonCode: the connection result
    :param properties: properties returned from the broker
    """
    if reasonCode == mqtt.MQTT_ERR_SUCCESS:
        print("Success: Connection has been established!")
        client.subscribe("lock/lock", config_options["mqtt_qos"])
        client.subscribe("lock/unlock", config_options["mqtt_qos"])
        client.subscribe("lock/password/temp/activate", config_options["mqtt_qos"])
        client.subscribe("lock/password/temp/deactivate", config_options["mqtt_qos"])
    else:
        print(f"Failure: Connection could not be established!")


# =====================================================================================================================
#                                               MQTT Callback Configuration
# =====================================================================================================================
slock.on_connect = on_connect
slock.message_callback_add("lock/lock", toggle_lock)
slock.message_callback_add("lock/unlock", toggle_lock)
slock.message_callback_add("lock/password/temp/activate", toggle_temp_password)
slock.message_callback_add("lock/password/temp/deactivate", toggle_temp_password)

slock.loop_forever()  # Start Program Loop
