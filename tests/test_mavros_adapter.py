from adapters.mavros_adapter import MavrosAdapter


def test_mavros_adapter_is_constructible_without_ros_imports():
    adapter = MavrosAdapter()
    assert adapter.name == "mavros"
    assert adapter.is_connected() is False
    assert adapter.get_position().to_list() == [0.0, 0.0, 0.0]


def test_mavros_adapter_registration():
    from adapters.adapter_manager import list_adapters

    names = {item["name"] for item in list_adapters()}
    assert "mavros" in names
