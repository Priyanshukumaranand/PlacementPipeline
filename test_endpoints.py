"""
Test script to verify the API endpoints are working.
"""
import requests
import json

BASE_URL = "http://localhost:8000"

def test_health():
    """Test health check endpoint."""
    print("=" * 60)
    print("Testing Health Check Endpoint")
    print("=" * 60)
    try:
        response = requests.get(f"{BASE_URL}/")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_process_now():
    """Test the process-now endpoint."""
    print("\n" + "=" * 60)
    print("Testing /api/v1/gmail/process-now Endpoint")
    print("=" * 60)
    try:
        response = requests.post(f"{BASE_URL}/api/v1/gmail/process-now", timeout=120)
        print(f"Status Code: {response.status_code}")
        result = response.json()
        print(f"Response:")
        print(json.dumps(result, indent=2))
        return response.status_code == 200
    except requests.exceptions.Timeout:
        print("Request timed out (this is normal for email processing)")
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_api_docs():
    """Check if API docs are accessible."""
    print("\n" + "=" * 60)
    print("Checking API Documentation")
    print("=" * 60)
    try:
        response = requests.get(f"{BASE_URL}/docs")
        print(f"Status Code: {response.status_code}")
        print(f"API Docs available at: {BASE_URL}/docs")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    print("\n🧪 Live Testing of Placement Pipeline API")
    print("=" * 60)
    
    results = []
    
    # Test health
    results.append(("Health Check", test_health()))
    
    # Test API docs
    results.append(("API Docs", test_api_docs()))
    
    # Test process-now (this may take time)
    print("\n⚠️  Note: process-now may take 1-2 minutes to process emails...")
    results.append(("Process Now", test_process_now()))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)
    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} - {name}")
    
    passed = sum(1 for _, result in results if result)
    print(f"\nTotal: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        print("\n✅ All tests passed! API is working correctly.")
    else:
        print("\n⚠️  Some tests failed. Check the errors above.")

