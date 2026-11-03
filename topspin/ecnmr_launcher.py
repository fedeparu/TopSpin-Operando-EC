# TopSpin Jython 2.7 user script. Also syntax-checkable by Python 3.
# Site-dependent integration: validate against the installed TopSpin manual.
# Set ECNMR_HOME to this repository and optionally ECNMR_PYTHON before TopSpin starts.
# This script only opens the offline viewer; it does not start an acquisition.
import os


def dataset_directory(current):
    """Resolve the conventional CURDATA [name, expno, procno, data-root] tuple."""
    if not current or len(current) < 4:
        raise ValueError("TopSpin did not return a current dataset.")
    return os.path.join(str(current[3]), str(current[0]), str(current[1]))


def main():
    project = os.environ.get("ECNMR_HOME", "")
    if not project or not os.path.isdir(project):
        raise ValueError("Set ECNMR_HOME to the installed EC-NMR repository before starting TopSpin.")
    executable = os.environ.get("ECNMR_PYTHON", "")
    if not executable:
        executable = os.path.join(project, ".venv", "Scripts", "python.exe")
        if not os.path.isfile(executable):
            executable = os.path.join(project, ".venv", "bin", "python")
    if not os.path.isfile(executable):
        raise ValueError("Run the EC-NMR installer or set ECNMR_PYTHON to its Python executable.")
    import TopCmds
    current = TopCmds.CURDATA()  # Supplied by TopSpin, never invoked by the service.
    dataset = dataset_directory(current)
    arguments = [executable, "-m", "ecnmr", "--open", "--port", "8765"]
    if os.path.isdir(dataset):
        arguments.extend(["--nmr", dataset])
    # Java argv API avoids platform shell quoting and works inside Jython.
    from java.io import File
    from java.lang import ProcessBuilder
    from java.util import ArrayList
    command = ArrayList()
    for argument in arguments:
        command.add(argument)
    builder = ProcessBuilder(command)
    builder.directory(File(project))
    builder.redirectErrorStream(True)
    log_path = os.path.join(project, "work", "topspin-launch.log")
    if not os.path.isdir(os.path.dirname(log_path)):
        os.makedirs(os.path.dirname(log_path))
    builder.redirectOutput(File(log_path))
    builder.start()
    TopCmds.MSG("Opening EC-NMR viewer. Launch log: " + log_path)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        try:
            import TopCmds
            TopCmds.MSG("EC-NMR launcher: " + str(error))
        except ImportError:
            raise error
