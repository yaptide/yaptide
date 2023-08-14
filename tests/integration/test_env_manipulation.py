import os

def test_clean_enviroment(yaptide_bin_dir):
    """Test we can run simulations"""
    assert os.environ['PATH']
    path_parts = os.environ['PATH'].split(os.pathsep)
    assert str(yaptide_bin_dir) != path_parts[0]
    assert str(yaptide_bin_dir) not in path_parts

def test_modified_enviroment(yaptide_bin_dir, add_simulators_to_path_variable):
    """Test we can run simulations"""
    assert os.environ['PATH']
    path_parts = os.environ['PATH'].split(os.pathsep)
    assert str(yaptide_bin_dir) == path_parts[0]
    assert str(yaptide_bin_dir) in path_parts

def test_subsequent_for_clean_enviroment(yaptide_bin_dir):
    """Test we can run simulations"""
    assert os.environ['PATH']
    path_parts = os.environ['PATH'].split(os.pathsep)
    assert str(yaptide_bin_dir) != path_parts[0]
    assert str(yaptide_bin_dir) not in path_parts
