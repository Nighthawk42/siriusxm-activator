#!/usr/bin/env python3
import os
import json
import uuid
import logging
from logging.handlers import RotatingFileHandler
import requests
from datetime import datetime
from requests.exceptions import RequestException
from typing import Optional, Dict, Any

class APIError(Exception):
    """Custom exception class for API errors."""
    pass

class SiriusXMClient:
    """
    Client to interact with SiriusXM API endpoints.
    Manages configuration, activation logging, and the core API calls.
    """
    API_BASE_URL = "https://dealerapp.siriusxm.com"
    LOGIN_ENDPOINT = "/authService/100000002/login"
    VERSION_CONTROL_ENDPOINT = "/services/DealerAppService7/VersionControl"
    GET_PROPERTIES_ENDPOINT = "/services/DealerAppService7/getProperties"
    SAT_REFRESH_ENDPOINT = "/services/USUpdateDeviceSATRefresh/updateDeviceSATRefreshWithPriority"
    CRM_INFO_ENDPOINT = "/services/DemoConsumptionRules/GetCRMAccountPlanInformation"
    DB_UPDATE_ENDPOINT = "/services/DBSuccessUpdate/DBUpdateForGoogle"
    BLOCKLIST_ENDPOINT = "/services/USBlockListDevice/BlockListDevice"
    CREATE_ACCOUNT_ENDPOINT = "/services/DealerAppService3/CreateAccount"
    REFRESH_FOR_CC_ENDPOINT = "/services/USUpdateDeviceRefreshForCC/updateDeviceSATRefreshWithPriority"
    ORACLE_URL = "https://oemremarketing.custhelp.com/cgi-bin/oemremarketing.cfg/php/custom/src/oracle/program_status.php"
    REQUEST_TIMEOUT = 10  # seconds

    def __init__(self, config_file: str = "config.json", activation_log_file: str = "activation_log.json") -> None:
        self.config_file = config_file
        self.activation_log_file = activation_log_file
        self.config = self._load_or_create_config()
        self.activation_log = self._load_activation_log()
        self.session = requests.Session()
        self.auth_token: Optional[str] = None
        self.sequence_value: Optional[str] = None
        # Persist the device ID for consistency between runs.
        self.device_id = self._get_or_create_device_id()

    def _get_or_create_device_id(self) -> str:
        if "device_id" in self.config:
            return self.config["device_id"]
        new_device_id = str(uuid.uuid4())
        self.config["device_id"] = new_device_id
        self._save_config()
        return new_device_id

    def _load_or_create_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as file:
                    config = json.load(file)
                    if "configurations" not in config or not isinstance(config["configurations"], list):
                        raise ValueError("Missing or invalid 'configurations' list.")
                    return config
            except (json.JSONDecodeError, ValueError) as e:
                logging.error("Error loading config file '%s': %s", self.config_file, e)
                print(f"Error: Invalid configuration file '{self.config_file}': {e}")
        return {"configurations": []}

    def _save_config(self) -> None:
        try:
            with open(self.config_file, "w") as file:
                json.dump(self.config, file, indent=4)
            logging.info("Configuration successfully saved to '%s'.", self.config_file)
        except IOError as e:
            logging.error("Failed to save configuration: %s", e)
            print(f"Error: Could not save configuration: {e}")

    def _load_activation_log(self) -> Dict[str, Any]:
        if os.path.exists(self.activation_log_file):
            try:
                with open(self.activation_log_file, "r") as file:
                    return json.load(file)
            except (json.JSONDecodeError, ValueError) as e:
                logging.error("Error loading activation log file '%s': %s", self.activation_log_file, e)
                print(f"Error: Invalid activation log file '{self.activation_log_file}': {e}")
        return {}

    def _save_activation_log(self) -> None:
        try:
            with open(self.activation_log_file, "w") as file:
                json.dump(self.activation_log, file, indent=4)
            logging.info("Activation log successfully saved to '%s'.", self.activation_log_file)
        except IOError as e:
            logging.error("Failed to save activation log: %s", e)
            print(f"Error: Could not save activation log: {e}")

    def add_configuration(self) -> Dict[str, str]:
        print("Adding a new configuration entry:")
        while True:
            radio_id = input("Enter Radio ID: ").strip().upper()
            if radio_id:
                break
            print("Radio ID cannot be empty. Please try again.")
        make = input("Enter Vehicle Make: ").strip()
        model = input("Enter Vehicle Model: ").strip()
        while True:
            year = input("Enter Vehicle Year (YYYY): ").strip()
            if year.isdigit() and len(year) == 4:
                break
            print("Year must be a 4-digit number. Please try again.")
        new_config = {"RadioID": radio_id, "Make": make, "Model": model, "Year": year}
        self.config["configurations"].append(new_config)
        self._save_config()
        return new_config

    def select_configuration(self) -> Dict[str, str]:
        if not self.config["configurations"]:
            print("No configurations available. Please add one.")
            return self.add_configuration()
        print("Available configurations:")
        for index, conf in enumerate(self.config["configurations"], start=1):
            radio = conf["RadioID"]
            if radio in self.activation_log:
                status = "Activated"
                last_act = self.activation_log[radio].get("last_activated", "N/A")
            else:
                status = "Not Activated"
                last_act = "N/A"
            print(f"{index}. {conf['Make']} {conf['Model']} ({conf['Year']}) - Radio ID: {radio} [{status} | Last: {last_act}]")
        while True:
            try:
                choice = int(input("Select a configuration by number (or 0 to add a new one): "))
                if choice == 0:
                    return self.add_configuration()
                elif 1 <= choice <= len(self.config["configurations"]):
                    return self.config["configurations"][choice - 1]
                else:
                    print("Invalid selection. Please try again.")
            except ValueError:
                print("Invalid input. Please enter a numeric value.")

    def _build_default_headers(self, extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-us",
            "Accept-Encoding": "br, gzip, deflate",
            "User-Agent": "SiriusXM Dealer/3.1.0 CFNetwork/1568.200.51 Darwin/24.1.0",
            "X-Voltmx-API-Version": "1.0",
            "X-Voltmx-DeviceId": self.device_id,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if self.auth_token:
            headers["X-Voltmx-Authorization"] = self.auth_token
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _make_request(self, method: str, url: str, headers: Dict[str, str],
                      data: Optional[Dict[str, Any]] = None,
                      params: Optional[Dict[str, Any]] = None) -> requests.Response:
        try:
            response = self.session.request(method, url, headers=headers, data=data, params=params, timeout=self.REQUEST_TIMEOUT)
            response.raise_for_status()
            logging.info("Request to %s succeeded with status %s.", url, response.status_code)
            return response
        except RequestException as error:
            logging.error("Request to %s failed: %s", url, error)
            raise APIError(f"Request to {url} failed: {error}")

    def _post(self, endpoint: str, data: Dict[str, Any],
              extra_headers: Optional[Dict[str, str]] = None,
              params: Optional[Dict[str, Any]] = None) -> requests.Response:
        url = self.API_BASE_URL + endpoint if endpoint.startswith("/") else endpoint
        headers = self._build_default_headers(extra_headers)
        return self._make_request("POST", url, headers=headers, data=data, params=params)

    def login_user(self) -> None:
        print("User Login")
        extra_headers = {
            "X-Voltmx-Platform-Type": "ios",
            "X-Voltmx-SDK-Type": "js",
            "X-Voltmx-SDK-Version": "9.5.36",
            "X-Voltmx-App-Key": os.getenv("SIRIUSXM_APP_KEY", "67cfe0220c41a54cb4e768723ad56b41"),
            "X-Voltmx-App-Secret": os.getenv("SIRIUSXM_APP_SECRET", "c086fca8646a72cf391f8ae9f15e5331"),
        }
        try:
            response = self._post(self.LOGIN_ENDPOINT, data={}, extra_headers=extra_headers)
            data_resp = response.json()
            token = data_resp.get("claims_token", {}).get("value")
            if token:
                self.auth_token = token
                logging.info("User successfully authenticated.")
                print("✓ Login successful.")
            else:
                raise APIError("Authentication token missing in response.")
        except (APIError, json.JSONDecodeError) as error:
            logging.error("Failed to login: %s", error)
            print("✗ Error: Could not process login response.")
            raise

    def perform_version_check(self) -> None:
        print("Version Check")
        data = {
            "deviceCategory": "iPhone",
            "appver": "3.1.0",
            "deviceLocale": "en_US",
            "deviceModel": "iPhone 6 Plus",
            "deviceVersion": "12.5.7",
            "deviceType": "",
        }
        try:
            response = self._post(self.VERSION_CONTROL_ENDPOINT, data=data)
            logging.debug("Version check response: %s", response.text)
        except APIError as e:
            logging.error("Version check failed: %s", e)
            raise

    def retrieve_device_properties(self) -> None:
        print("Retrieve Device Properties")
        try:
            response = self._post(self.GET_PROPERTIES_ENDPOINT, data={})
            logging.debug("Device properties response: %s", response.text)
        except APIError as e:
            logging.error("Failed to retrieve device properties: %s", e)
            raise

    def update_device_status(self, radio_id: str) -> None:
        print("Update Device Status (SAT Refresh)")
        data = {
            "deviceId": radio_id,
            "appVersion": "3.1.0",
            "lng": "-86.210313195",
            "deviceID": self.device_id,
            "provisionPriority": "2",
            "provisionType": "activate",
            "lat": "32.37436705",
        }
        try:
            response = self._post(self.SAT_REFRESH_ENDPOINT, data=data)
            resp_json = response.json()
            self.sequence_value = resp_json.get("seqValue")
            if self.sequence_value:
                logging.info("Sequence value retrieved: %s", self.sequence_value)
                print("✓ Device status updated successfully.")
            else:
                raise APIError("Missing sequence value in response.")
        except (APIError, json.JSONDecodeError) as e:
            logging.error("Failed to update device status: %s", e)
            print("✗ Error: Device update response could not be processed.")
            raise

    def fetch_crm_information(self, radio_id: str) -> None:
        print("Retrieve CRM Account Plan Information")
        data = {"seqVal": self.sequence_value, "deviceId": radio_id}
        try:
            response = self._post(self.CRM_INFO_ENDPOINT, data=data)
            logging.debug("CRM information response: %s", response.text)
        except APIError as e:
            logging.error("Failed to fetch CRM information: %s", e)
            raise

    def update_google_database(self, radio_id: str) -> None:
        print("Update Google Database")
        data = {
            "OM_ELIGIBILITY_STATUS": "Eligible",
            "appVersion": "3.1.0",
            "flag": "failure",
            "Radio_ID": radio_id,
            "deviceID": self.device_id,
            "G_PLACES_REQUEST": "",
            "OS_Version": "iPhone 12.5.7",
            "G_PLACES_RESPONSE": "",
            "Confirmation_Status": "SUCCESS",
            "seqVal": self.sequence_value,
        }
        try:
            response = self._post(self.DB_UPDATE_ENDPOINT, data=data)
            logging.debug("Google database update response: %s", response.text)
        except APIError as e:
            logging.error("Failed to update Google database: %s", e)
            raise

    def block_device(self) -> None:
        print("Block Device")
        data = {"deviceId": self.device_id}
        try:
            response = self._post(self.BLOCKLIST_ENDPOINT, data=data)
            logging.debug("Device block response: %s", response.text)
        except APIError as e:
            logging.error("Failed to block device: %s", e)
            raise

    def perform_oracle_check(self) -> None:
        print("Oracle Program Status Check")
        params = {"google_addr": "395 EASTERN BLVD, MONTGOMERY, AL 36117, USA"}
        try:
            # ORACLE_URL is a full URL so we use _make_request directly.
            headers = self._build_default_headers({"Content-Type": "application/x-www-form-urlencoded"})
            response = self._make_request("POST", self.ORACLE_URL, headers=headers, data={}, params=params)
            logging.debug("Oracle program status response: %s", response.text)
        except APIError as e:
            logging.error("Oracle check failed: %s", e)
            raise

    def create_new_account(self, radio_id: str) -> None:
        print("Create New Account")
        data = {
            "seqVal": self.sequence_value,
            "deviceId": radio_id,
            "oracleCXFailed": "1",
            "appVersion": "3.1.0",
        }
        try:
            response = self._post(self.CREATE_ACCOUNT_ENDPOINT, data=data)
            logging.debug("Account creation response: %s", response.text)
        except APIError as e:
            logging.error("Account creation failed: %s", e)
            raise

    def refresh_device_status_for_cc(self, radio_id: str) -> None:
        print("Refresh Device Status for CC")
        data = {
            "deviceId": radio_id,
            "provisionPriority": "2",
            "appVersion": "3.1.0",
            "device_Type": "iPhone iPhone 6 Plus",
            "deviceID": self.device_id,
            "os_Version": "iPhone 12.5.7",
            "provisionType": "activate",
        }
        try:
            response = self._post(self.REFRESH_FOR_CC_ENDPOINT, data=data)
            logging.debug("Device status refresh for CC response: %s", response.text)
        except APIError as e:
            logging.error("Refresh device status for CC failed: %s", e)
            raise

    def mark_configuration_as_activated(self, configuration: Dict[str, str]) -> None:
        """Mark the configuration as activated and record the activation timestamp (ISO 8601)."""
        timestamp = datetime.now().isoformat()
        radio = configuration["RadioID"]
        self.activation_log[radio] = {"activated": True, "last_activated": timestamp}
        self._save_activation_log()
        logging.info("Configuration for Radio ID %s marked as activated on %s", radio, timestamp)
        print(f"Configuration marked as activated on {timestamp}")

def main() -> None:
    logging.info("================================================")
    logging.info("New run started at: %s", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    
    client = SiriusXMClient()
    
    while True:
        try:
            selected_config = client.select_configuration()
            radio_id = selected_config["RadioID"]
            print(f"Selected configuration: {selected_config['Make']} {selected_config['Model']} ({selected_config['Year']}) - Radio ID: {radio_id}")
        
            if radio_id in client.activation_log:
                last_act = client.activation_log[radio_id].get("last_activated", "unknown")
                print(f"This configuration was already activated on {last_act}.")
                choice = input("Do you want to force reactivation? (y/N): ").strip().lower()
                if choice != "y":
                    print("Activation skipped.")
                    input("Press any key to return to configuration selection...")
                    continue
        
            print("Starting the SiriusXM API workflow...")
            try:
                client.login_user()
                client.perform_version_check()
                client.retrieve_device_properties()
                client.update_device_status(radio_id)
                client.fetch_crm_information(radio_id)
                client.update_google_database(radio_id)
                client.block_device()
                client.perform_oracle_check()
                client.create_new_account(radio_id)
                client.refresh_device_status_for_cc(radio_id)
                client.mark_configuration_as_activated(selected_config)
                print("✓ SiriusXM activation completed successfully.")
            except APIError as e:
                print(f"Workflow terminated due to error: {e}")
            input("Press any key to return to configuration selection (or Ctrl+C to exit)...")
        except KeyboardInterrupt:
            print("\nExiting...")
            break

if __name__ == "__main__":
    # Configure logging with a rotating file handler.
    log_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    log_file = "activation.log"
    handler = RotatingFileHandler(log_file, mode='a', maxBytes=5 * 1024 * 1024,
                                  backupCount=2, encoding=None, delay=0)
    handler.setFormatter(log_formatter)
    handler.setLevel(logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    
    main()
